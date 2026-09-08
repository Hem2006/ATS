"""
Stitch ATS — Hiring Agent Orchestrator

An autonomous agent that pursues a hiring goal end-to-end:
    observe → decide → act → evaluate → adapt

Instead of a hard-coded pipeline, the agent uses an LLM to CHOOSE its next
tool from a registry on every step, driven purely by the current state of
the candidate pool for a given job.

Design goals:
  * Every thought, tool call, observation, and adaptation is persisted
    to the AgentStep table AND streamed live via the agent event bus.
  * Robust to LLM failures — every tool degrades gracefully so the
    demo never crashes.
  * Three concrete adaptations are baked in: thin pool, ghosting,
    weak-quality outliers.
  * Ends with a self-verifier judge and a final outcome summary.
"""
from __future__ import annotations

import json
import secrets
import threading
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Dict, List, Optional

from sqlalchemy.orm import Session

from ..database import SessionLocal
from ..tenant import current_company_id
from ..models import (
    AgentRun,
    AgentStep,
    Candidate,
    Job,
    Screening,
    Interview,
    Activity,
    CommunicationLog,
)
from .agent_events import get_bus, close_bus
from .ai_screening import (
    screen_single_candidate,
    safe_chat_completion,
    clean_json_response,
)
from .assessment_eval import (
    generate_candidate_assessment_questions,
    grade_assessment,
)
from .verifier import verify_shortlist


# ---------------------------------------------------------------------------
# Agent configuration
# ---------------------------------------------------------------------------

MAX_STEPS = 12
DEFAULT_SHORTLIST_SIZE = 3
DEFAULT_PASSING_THRESHOLD = 70.0
LOOSENED_THRESHOLD = 55.0
GHOST_HOURS = 24  # after this many hours a pending assessment is "ghosted"


# ---------------------------------------------------------------------------
# Persisted step helpers
# ---------------------------------------------------------------------------


def _record_step(
    db: Session,
    run: AgentRun,
    step_index: int,
    kind: str,
    content: str = "",
    tool_name: Optional[str] = None,
    payload: Any = None,
) -> AgentStep:
    """Persist an AgentStep row and broadcast it on the event bus."""
    step = AgentStep(
        run_id=run.id,
        step_index=step_index,
        kind=kind,
        tool_name=tool_name,
        content=content[:8000] if content else content,
        payload=json.dumps(payload, default=str) if payload is not None else None,
    )
    db.add(step)
    db.commit()
    db.refresh(step)

    event = {
        "id": step.id,
        "run_id": run.id,
        "step_index": step_index,
        "kind": kind,
        "tool_name": tool_name,
        "content": content,
        "payload": payload,
        "created_at": step.created_at.isoformat() if step.created_at else None,
    }
    get_bus(run.id).publish(event)
    return step


# ---------------------------------------------------------------------------
# Tool implementations
#
# Each tool has the signature:  fn(agent: HiringAgent, args: dict) -> dict
# The returned dict is the "observation" the agent sees on the next step.
# ---------------------------------------------------------------------------


def _tool_get_pool_stats(agent: "HiringAgent", args: Dict[str, Any]) -> Dict[str, Any]:
    """Return a snapshot of the current candidate pool for the target job."""
    job = agent.db.query(Job).filter(Job.id == agent.job_id).first()
    candidates = agent.db.query(Candidate).filter(Candidate.role == job.title).all()

    strong = [c for c in candidates if (c.match_score or 0) >= agent.passing_threshold]
    weak = [c for c in candidates if 0 < (c.match_score or 0) < agent.passing_threshold]
    unscored = [c for c in candidates if not c.match_score]

    pending_assessment = [
        c for c in candidates if c.assessment_status == "pending"
    ]

    return {
        "total_candidates": len(candidates),
        "strong_candidates": len(strong),
        "weak_candidates": len(weak),
        "unscored_candidates": len(unscored),
        "assessment_pending": len(pending_assessment),
        "passing_threshold": agent.passing_threshold,
        "target_shortlist_size": agent.target_shortlist_size,
        "strong_names": [c.name for c in strong],
    }


def _tool_score_unscored_candidates(agent: "HiringAgent", args: Dict[str, Any]) -> Dict[str, Any]:
    """Screen any candidate for this job that has not been scored yet."""
    job = agent.db.query(Job).filter(Job.id == agent.job_id).first()
    unscored = (
        agent.db.query(Candidate)
        .filter(Candidate.role == job.title)
        .filter(Candidate.match_score.is_(None))
        .all()
    )
    if not unscored:
        return {"scored": 0, "message": "No unscored candidates."}

    results = []
    for c in unscored[:10]:  # bounded batch
        result = screen_single_candidate(job.description, c.resume_text or "", c.name)
        # Floor at 1.0 so a failed-LLM screening still counts as 'scored' and
        # we don't loop forever trying to re-score the same candidate.
        c.match_score = max(1.0, float(result["match_score"] or 0.0))
        c.rejection_reason = result.get("rejection_reason")
        c.status = "screened"

        screening = Screening(
            job_id=job.id,
            candidate_id=c.id,
            match_score=result["match_score"],
            strengths=result["strengths"],
            gaps=result["gaps"],
            overall_summary=result["overall_summary"],
            seniority_fit=result["seniority_fit"],
            rejection_reason=result.get("rejection_reason"),
            score_justification=result.get("score_justification"),
            jd_vs_cv_score=result.get("jd_vs_cv_score"),
            jd_vs_linkedin_score=result.get("jd_vs_linkedin_score"),
            jd_vs_github_score=result.get("jd_vs_github_score"),
        )
        agent.db.add(screening)
        results.append({"name": c.name, "score": result["match_score"]})
    agent.db.commit()

    return {"scored": len(results), "results": results}


def _tool_loosen_criteria(agent: "HiringAgent", args: Dict[str, Any]) -> Dict[str, Any]:
    """
    ADAPTATION: The pool is too thin at the current threshold.
    Drop the passing bar and re-count how many candidates now qualify.
    """
    previous = agent.passing_threshold
    new_threshold = float(args.get("new_threshold", LOOSENED_THRESHOLD))
    # Never go below 45 — refuse to hire completely unfit candidates.
    new_threshold = max(45.0, min(new_threshold, previous - 5))
    agent.passing_threshold = new_threshold
    agent._adaptation_count += 1

    job = agent.db.query(Job).filter(Job.id == agent.job_id).first()
    now_strong = (
        agent.db.query(Candidate)
        .filter(Candidate.role == job.title)
        .filter(Candidate.match_score >= new_threshold)
        .count()
    )
    return {
        "adaptation": "loosen_criteria",
        "previous_threshold": previous,
        "new_threshold": new_threshold,
        "candidates_now_qualifying": now_strong,
        "note": "Threshold lowered because the pool of qualified candidates was too thin.",
    }


def _tool_request_more_sourcing(agent: "HiringAgent", args: Dict[str, Any]) -> Dict[str, Any]:
    """
    ADAPTATION: In a real deployment this would trigger a LinkedIn / GitHub
    sourcing job. We surface the request as an activity for the recruiter to
    action — we do NOT invent fake candidates, since a shortlist full of
    "Sourced Candidate ABCD" placeholders is useless.
    """
    agent._adaptation_count += 1
    job = agent.db.query(Job).filter(Job.id == agent.job_id).first()

    activity = Activity(
        action="Sourcing queued by agent",
        description=f"Hiring Agent flagged the pool as too thin for '{job.title}' — recruiter action requested.",
        icon="🤖",
        color="#6366f1",
    )
    agent.db.add(activity)
    agent.db.commit()

    return {
        "adaptation": "request_more_sourcing",
        "note": "Sourcing request queued for the recruiter. No fake candidates added — the agent moves on with the current pool.",
    }


def _tool_generate_assessment(agent: "HiringAgent", args: Dict[str, Any]) -> Dict[str, Any]:
    """Generate a personalized 10-question assessment for a candidate."""
    candidate_id = args.get("candidate_id")
    if not candidate_id:
        return {"error": "candidate_id is required."}

    candidate = agent.db.query(Candidate).filter(Candidate.id == candidate_id).first()
    if not candidate:
        return {"error": f"No candidate with id {candidate_id}."}

    job = agent.db.query(Job).filter(Job.id == agent.job_id).first()
    questions = generate_candidate_assessment_questions(
        job.title, job.description, candidate.name, candidate.resume_text or ""
    )
    candidate.assessment_questions = json.dumps(questions)
    candidate.assessment_status = "pending"
    candidate.assessment_token = secrets.token_urlsafe(16)
    # Mark timestamp so the ghosting detector has a reference.
    candidate.offer_date = datetime.now(timezone.utc)  # reused as "invited_at"
    agent.db.commit()

    return {
        "candidate_id": candidate.id,
        "candidate_name": candidate.name,
        "questions_generated": len(questions),
        "assessment_link": f"/candidate-assessment/{candidate.assessment_token}",
    }


def _tool_simulate_candidate_responses(agent: "HiringAgent", args: Dict[str, Any]) -> Dict[str, Any]:
    """
    Demo helper: simulate a candidate submitting answers so the agent
    can practice grading + adaptation end-to-end without waiting for a human.
    """
    candidate_id = args.get("candidate_id")
    quality = args.get("quality", "good")  # good | weak | ghost

    candidate = agent.db.query(Candidate).filter(Candidate.id == candidate_id).first()
    if not candidate:
        return {"error": f"No candidate with id {candidate_id}."}

    if quality == "ghost":
        # Back-date the invite so it registers as ghosted.
        candidate.offer_date = datetime.now(timezone.utc) - timedelta(hours=GHOST_HOURS + 2)
        agent.db.commit()
        return {"candidate": candidate.name, "quality": "ghost", "note": "Left pending."}

    questions = json.loads(candidate.assessment_questions or "[]")
    if quality == "weak":
        answers = ["idk", "n/a", "", "not sure", "pass", "-", "?", "no", "skip", "meh"][: len(questions)]
    else:
        answers = [
            f"I would approach this by leveraging my {agent.job_title} experience: "
            "start by understanding the requirement, prototype quickly, then iterate with tests."
        ] * len(questions)

    job = agent.db.query(Job).filter(Job.id == agent.job_id).first()
    graded = grade_assessment(job.title, job.description, questions, answers)
    candidate.assessment_responses = json.dumps({"answers": answers, "grading": graded})
    candidate.assessment_score = graded.get("score", 0.0)
    candidate.assessment_status = graded.get("status", "failed")
    agent.db.commit()

    return {
        "candidate": candidate.name,
        "quality": quality,
        "assessment_score": graded.get("score"),
        "assessment_status": graded.get("status"),
    }


def _tool_check_for_ghosted_candidates(agent: "HiringAgent", args: Dict[str, Any]) -> Dict[str, Any]:
    """
    ADAPTATION detector: any candidate whose assessment has been pending
    longer than GHOST_HOURS is considered ghosted.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(hours=GHOST_HOURS)
    job = agent.db.query(Job).filter(Job.id == agent.job_id).first()
    candidates = (
        agent.db.query(Candidate)
        .filter(Candidate.role == job.title)
        .filter(Candidate.assessment_status == "pending")
        .all()
    )
    ghosted = []
    for c in candidates:
        invited_at = c.offer_date
        if invited_at is None:
            continue
        if invited_at.tzinfo is None:
            invited_at = invited_at.replace(tzinfo=timezone.utc)
        if invited_at <= cutoff:
            ghosted.append({"id": c.id, "name": c.name})
    return {"ghosted_count": len(ghosted), "ghosted": ghosted}


def _tool_send_reminder(agent: "HiringAgent", args: Dict[str, Any]) -> Dict[str, Any]:
    """ADAPTATION: nudge a ghosting candidate before giving up on them."""
    candidate_id = args.get("candidate_id")
    candidate = agent.db.query(Candidate).filter(Candidate.id == candidate_id).first()
    if not candidate:
        return {"error": f"No candidate with id {candidate_id}."}

    agent._adaptation_count += 1
    log = CommunicationLog(
        candidate_id=candidate.id,
        type="email",
        subject=f"Reminder: Complete your {agent.job_title} assessment",
        body=(
            f"Hi {candidate.name},\n\n"
            "We noticed you haven't completed the technical assessment yet. "
            "If you're still interested, please finish it in the next 24 hours "
            "so we can move your application forward.\n\nThanks,\nHiring Agent"
        ),
        sender="Hiring Agent",
        recipient=candidate.email or "unknown",
    )
    agent.db.add(log)
    # Reset invited_at so ghosting is measured from the reminder.
    candidate.offer_date = datetime.now(timezone.utc)
    agent.db.commit()
    return {
        "adaptation": "send_reminder",
        "candidate": candidate.name,
        "message": "Reminder queued.",
    }


def _tool_drop_candidate(agent: "HiringAgent", args: Dict[str, Any]) -> Dict[str, Any]:
    """Give up on a candidate that ghosted after reminder."""
    candidate_id = args.get("candidate_id")
    candidate = agent.db.query(Candidate).filter(Candidate.id == candidate_id).first()
    if not candidate:
        return {"error": f"No candidate with id {candidate_id}."}
    candidate.status = "rejected"
    candidate.rejection_reason = "Did not respond to assessment reminder."
    candidate.assessment_status = "abandoned"
    agent.db.commit()
    return {"dropped": candidate.name}


def _tool_regenerate_harder_questions(agent: "HiringAgent", args: Dict[str, Any]) -> Dict[str, Any]:
    """
    ADAPTATION: assessment scores look inflated — regenerate a harder set
    so future candidates get a stronger signal.
    """
    candidate_id = args.get("candidate_id")
    candidate = agent.db.query(Candidate).filter(Candidate.id == candidate_id).first()
    if not candidate:
        return {"error": f"No candidate with id {candidate_id}."}

    agent._adaptation_count += 1
    job = agent.db.query(Job).filter(Job.id == agent.job_id).first()
    harder_prompt = (
        f"{job.description}\n\n"
        "ADDITIONAL DIFFICULTY CONSTRAINT: Focus on senior-level, deep systems questions. "
        "Avoid basic definitions. Prefer trade-off analysis, failure modes, and design decisions."
    )
    questions = generate_candidate_assessment_questions(
        job.title, harder_prompt, candidate.name, candidate.resume_text or ""
    )
    candidate.assessment_questions = json.dumps(questions)
    candidate.assessment_status = "pending"
    candidate.assessment_score = None
    candidate.assessment_responses = None
    agent.db.commit()

    return {
        "adaptation": "regenerate_harder_questions",
        "candidate": candidate.name,
        "questions_generated": len(questions),
    }


def _tool_schedule_interview(agent: "HiringAgent", args: Dict[str, Any]) -> Dict[str, Any]:
    """Schedule an interview slot for a candidate."""
    candidate_id = args.get("candidate_id")
    candidate = agent.db.query(Candidate).filter(Candidate.id == candidate_id).first()
    if not candidate:
        return {"error": f"No candidate with id {candidate_id}."}

    when = datetime.now(timezone.utc) + timedelta(days=2, hours=int(args.get("offset_hours", 10)))
    interview = Interview(
        candidate_id=candidate.id,
        interviewer_name=args.get("interviewer", "Hiring Panel"),
        scheduled_at=when,
        duration_mins=45,
        status="confirmed",
        panel_type=args.get("panel_type", "Technical"),
    )
    agent.db.add(interview)
    candidate.status = "interviewed"
    agent.db.commit()
    return {
        "candidate": candidate.name,
        "scheduled_at": when.isoformat(),
        "interviewer": interview.interviewer_name,
    }


def _tool_finalize_shortlist(agent: "HiringAgent", args: Dict[str, Any]) -> Dict[str, Any]:
    """
    Compose the final shortlist AND schedule an interview for each candidate
    in one shot. Doing both here keeps the run short: the agent's next step is
    always 'finish'.
    """
    job = agent.db.query(Job).filter(Job.id == agent.job_id).first()
    candidates = (
        agent.db.query(Candidate)
        .filter(Candidate.role == job.title)
        .filter(Candidate.match_score >= agent.passing_threshold)
        .order_by(Candidate.match_score.desc())
        .limit(agent.target_shortlist_size)
        .all()
    )

    shortlist = []
    scheduled = []
    for offset, c in enumerate(candidates):
        c.status = "shortlisted"
        latest = (
            agent.db.query(Screening)
            .filter(Screening.candidate_id == c.id)
            .order_by(Screening.id.desc())
            .first()
        )
        shortlist.append({
            "id": c.id,
            "name": c.name,
            "match_score": c.match_score,
            "seniority_fit": latest.seniority_fit if latest else None,
            "overall_summary": latest.overall_summary if latest else None,
        })

        # Auto-schedule an interview for each shortlisted candidate.
        when = datetime.now(timezone.utc) + timedelta(days=2, hours=10 + offset)
        interview = Interview(
            candidate_id=c.id,
            interviewer_name="Hiring Panel",
            scheduled_at=when,
            duration_mins=45,
            status="confirmed",
            panel_type="Technical",
        )
        agent.db.add(interview)
        scheduled.append({"candidate": c.name, "scheduled_at": when.isoformat()})

    agent.db.commit()
    agent._final_shortlist = shortlist
    return {
        "shortlist_size": len(shortlist),
        "shortlist": shortlist,
        "interviews_scheduled": len(scheduled),
        "scheduled": scheduled,
    }


def _tool_finish(agent: "HiringAgent", args: Dict[str, Any]) -> Dict[str, Any]:
    """Signal that the agent is done. Handled specially by the run loop."""
    return {"finish": True, "reason": args.get("reason", "goal reached")}


TOOL_REGISTRY: Dict[str, Dict[str, Any]] = {
    "get_pool_stats": {
        "fn": _tool_get_pool_stats,
        "description": "Snapshot of candidate pool: totals, strong/weak/unscored, pending assessments, current threshold.",
        "args": {},
    },
    "score_unscored_candidates": {
        "fn": _tool_score_unscored_candidates,
        "description": "Run AI screening on every candidate for the job that hasn't been scored yet.",
        "args": {},
    },
    "loosen_criteria": {
        "fn": _tool_loosen_criteria,
        "description": "ADAPTATION. Lower the passing threshold when the qualified pool is too thin. Args: {new_threshold: number}",
        "args": {"new_threshold": "float, e.g. 55"},
    },
    "request_more_sourcing": {
        "fn": _tool_request_more_sourcing,
        "description": "ADAPTATION. Pull additional candidates into the pool when even loosening didn't help.",
        "args": {},
    },
    "generate_assessment": {
        "fn": _tool_generate_assessment,
        "description": "Create a personalized 10-question technical assessment for a candidate. Args: {candidate_id: int}",
        "args": {"candidate_id": "int"},
    },
    "simulate_candidate_responses": {
        "fn": _tool_simulate_candidate_responses,
        "description": "Simulate a candidate submitting the assessment. Args: {candidate_id: int, quality: 'good'|'weak'|'ghost'}",
        "args": {"candidate_id": "int", "quality": "'good' | 'weak' | 'ghost'"},
    },
    "check_for_ghosted_candidates": {
        "fn": _tool_check_for_ghosted_candidates,
        "description": "Return any candidates whose assessment has been pending too long.",
        "args": {},
    },
    "send_reminder": {
        "fn": _tool_send_reminder,
        "description": "ADAPTATION. Send a reminder email to a ghosting candidate. Args: {candidate_id: int}",
        "args": {"candidate_id": "int"},
    },
    "drop_candidate": {
        "fn": _tool_drop_candidate,
        "description": "Reject a candidate that didn't respond after reminders. Args: {candidate_id: int}",
        "args": {"candidate_id": "int"},
    },
    "regenerate_harder_questions": {
        "fn": _tool_regenerate_harder_questions,
        "description": "ADAPTATION. Regenerate a harder assessment when scores look inflated. Args: {candidate_id: int}",
        "args": {"candidate_id": "int"},
    },
    "schedule_interview": {
        "fn": _tool_schedule_interview,
        "description": "Schedule a technical interview for a candidate. Args: {candidate_id: int, interviewer?: str, panel_type?: str, offset_hours?: int}",
        "args": {"candidate_id": "int"},
    },
    "finalize_shortlist": {
        "fn": _tool_finalize_shortlist,
        "description": "Mark the top N qualifying candidates as shortlisted AND schedule an interview for each in one shot. Call this exactly once when you're ready to conclude.",
        "args": {},
    },
    "finish": {
        "fn": _tool_finish,
        "description": "Terminate the run. Call this after finalize_shortlist. Args: {reason: str}",
        "args": {"reason": "str"},
    },
}


# ---------------------------------------------------------------------------
# The agent itself
# ---------------------------------------------------------------------------


SYSTEM_PROMPT = """You are an autonomous Hiring Agent inside an ATS.

Pursue the GOAL by calling ONE tool per step. Reply with EXACTLY this JSON:

{
  "thought": "<one short sentence explaining why>",
  "tool":    "<tool name>",
  "args":    { <tool arguments> }
}

Return ONLY that JSON. No markdown. No prose outside the JSON.

You are being watched by a recruiter — keep the run SHORT and MEANINGFUL.
A great run is 5-8 tool calls. Do NOT invent extra work.

STRICT PLAYBOOK (4-6 tool calls is a great run):
  1. get_pool_stats                       (always first)
  2. score_unscored_candidates            (if any unscored)
  3. If strong_candidates < target:
        loosen_criteria  (ONCE, if threshold is still above the floor)
        If still short: request_more_sourcing  (ONCE)
  4. finalize_shortlist                   (this ALSO schedules interviews — call it exactly ONCE)
  5. finish                               (immediately after finalize_shortlist)

FORBIDDEN in the default run (do not call — they belong to other flows):
  - generate_assessment
  - simulate_candidate_responses
  - regenerate_harder_questions
  - check_for_ghosted_candidates
  - send_reminder
  - drop_candidate
  - schedule_interview   (finalize_shortlist already does it)

Never repeat a tool that just produced no change. If the shortlist would be
empty, still call finalize_shortlist once and then finish.
"""


class HiringAgent:
    def __init__(
        self,
        db: Session,
        run: AgentRun,
        job: Job,
        goal: str,
        target_shortlist_size: int = DEFAULT_SHORTLIST_SIZE,
        passing_threshold: float = DEFAULT_PASSING_THRESHOLD,
    ):
        self.db = db
        self.run = run
        self.job_id = job.id
        self.job_title = job.title
        self.goal = goal
        self.target_shortlist_size = target_shortlist_size
        self.passing_threshold = passing_threshold
        self._adaptation_count = 0
        self._tool_calls = 0
        self._final_shortlist: List[Dict[str, Any]] = []
        self._history: List[Dict[str, Any]] = []
        self._step_index = 0

    def _next_step_index(self) -> int:
        self._step_index += 1
        return self._step_index

    def _tool_catalog(self) -> str:
        lines = []
        for name, spec in TOOL_REGISTRY.items():
            lines.append(f"- {name}: {spec['description']}")
        return "\n".join(lines)

    def _ask_next_action(self) -> Dict[str, Any]:
        """Ask the LLM to pick the next tool given current history."""
        history_lines = []
        for h in self._history[-8:]:  # bounded window
            history_lines.append(
                f"STEP {h['index']} — tool={h['tool']} args={json.dumps(h['args'])} "
                f"observation={json.dumps(h['observation'])[:400]}"
            )
        history_text = "\n".join(history_lines) if history_lines else "(none yet)"

        prompt = f"""GOAL: {self.goal}

TARGET JOB: {self.job_title} (id={self.job_id})
TARGET_SHORTLIST_SIZE: {self.target_shortlist_size}
CURRENT_PASSING_THRESHOLD: {self.passing_threshold}
ADAPTATIONS_MADE_SO_FAR: {self._adaptation_count}
TOOL_CALLS_SO_FAR: {self._tool_calls}

AVAILABLE TOOLS:
{self._tool_catalog()}

RECENT HISTORY:
{history_text}

Choose your next action. Return ONLY the JSON described in the system prompt.
"""
        try:
            resp = safe_chat_completion(
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.2,
                response_format={"type": "json_object"},
            )
            raw = resp.choices[0].message.content
            parsed = json.loads(clean_json_response(raw))
            if not isinstance(parsed, dict) or "tool" not in parsed:
                raise ValueError(f"LLM returned malformed action: {raw!r}")
            parsed.setdefault("thought", "")
            parsed.setdefault("args", {})
            if not isinstance(parsed["args"], dict):
                parsed["args"] = {}
            return parsed
        except Exception as e:
            # Fallback: rule-based decision so the demo never hangs.
            return self._fallback_action(str(e))

    def _fallback_action(self, error: str) -> Dict[str, Any]:
        """
        Deterministic backup when the LLM is unreachable or misbehaves.
        Progresses through the workflow phase-by-phase so the demo never hangs
        even if all model providers are down.
        """
        job = self.db.query(Job).filter(Job.id == self.job_id).first()
        candidates = self.db.query(Candidate).filter(Candidate.role == job.title).all()
        unscored = [c for c in candidates if c.match_score is None]
        strong = [c for c in candidates if (c.match_score or 0) >= self.passing_threshold]

        recent_tools = [h["tool"] for h in self._history[-3:]]

        def _pick(tool, thought, args=None):
            return {"thought": thought, "tool": tool, "args": args or {}}

        if not self._history:
            return _pick("get_pool_stats", f"LLM unavailable ({error[:80]}); start by observing pool.")

        # Phase 1: score anything unscored (but never twice in a row without progress)
        if unscored and recent_tools[-1:] != ["score_unscored_candidates"]:
            return _pick("score_unscored_candidates", "Fallback: score remaining candidates.")

        # Phase 2: pool thin → loosen
        if len(strong) < self.target_shortlist_size and self.passing_threshold > LOOSENED_THRESHOLD \
                and "loosen_criteria" not in recent_tools:
            return _pick("loosen_criteria", "Fallback: pool thin, loosen criteria.",
                         {"new_threshold": LOOSENED_THRESHOLD})

        # Phase 3: still thin → source more (max once)
        if len(strong) < self.target_shortlist_size and "request_more_sourcing" not in [h["tool"] for h in self._history]:
            return _pick("request_more_sourcing", "Fallback: still thin, source more.")

        # Phase 4: newly-sourced candidates need scoring
        if unscored:
            return _pick("score_unscored_candidates", "Fallback: score newly-sourced candidates.")

        # Phase 5: build shortlist
        if not self._final_shortlist:
            return _pick("finalize_shortlist", "Fallback: finalize shortlist.")

        # Phase 6: done
        return _pick("finish", "Fallback: wrap up.", {"reason": "fallback complete"})

    def run_loop(self) -> None:
        try:
            _record_step(
                self.db,
                self.run,
                self._next_step_index(),
                "thought",
                content=f"Agent started. Goal: {self.goal}",
                payload={"job_id": self.job_id, "job_title": self.job_title},
            )

            # Guard: if there are literally zero candidates for this job, the
            # agent can't do anything meaningful. Surface a helpful outcome
            # instead of pretending to work on an empty pool.
            total = (
                self.db.query(Candidate)
                .filter(Candidate.role == self.job_title)
                .count()
            )
            if total == 0:
                _record_step(
                    self.db, self.run, self._next_step_index(), "observation",
                    content=(
                        f"No candidates exist for '{self.job_title}' yet. "
                        f"Upload CVs on the AI Screening page (make sure their role field matches this job title), "
                        f"then re-run the agent."
                    ),
                )
                self._run_verifier()
                self._finalize_run(status="verified", note="No candidates in pool.")
                return

            same_tool_streak = 0
            last_tool = None
            for step in range(MAX_STEPS):
                action = self._ask_next_action()
                thought = action.get("thought", "")
                tool_name = action.get("tool")
                args = action.get("args", {})

                # Break the loop if the agent picks the same tool 4+ times in a row.
                if tool_name == last_tool:
                    same_tool_streak += 1
                else:
                    same_tool_streak = 0
                last_tool = tool_name
                if same_tool_streak >= 3:
                    forced = "finalize_shortlist" if not self._final_shortlist else "finish"
                    _record_step(
                        self.db, self.run, self._next_step_index(), "thought",
                        content=f"Repeat-guard: '{tool_name}' picked 4x in a row — forcing {forced}.",
                    )
                    tool_name = forced
                    args = {} if forced == "finalize_shortlist" else {"reason": "repeat-guard"}
                    same_tool_streak = 0
                    last_tool = tool_name

                # If the agent tries to call finalize_shortlist AGAIN after it
                # already produced a shortlist, quietly rewrite to finish so we
                # don't waste tokens re-listing the same names.
                if tool_name == "finalize_shortlist" and self._final_shortlist:
                    tool_name = "finish"
                    args = {"reason": "shortlist already finalized"}

                _record_step(
                    self.db,
                    self.run,
                    self._next_step_index(),
                    "thought",
                    content=thought,
                )

                if tool_name not in TOOL_REGISTRY:
                    _record_step(
                        self.db,
                        self.run,
                        self._next_step_index(),
                        "observation",
                        tool_name=tool_name,
                        content=f"Unknown tool '{tool_name}'. Skipping.",
                    )
                    continue

                _record_step(
                    self.db,
                    self.run,
                    self._next_step_index(),
                    "tool_call",
                    tool_name=tool_name,
                    content=f"Calling {tool_name}",
                    payload=args,
                )

                try:
                    observation = TOOL_REGISTRY[tool_name]["fn"](self, args)
                except Exception as tool_error:
                    observation = {"error": f"Tool raised: {tool_error}"}

                self._tool_calls += 1

                obs_kind = "adaptation" if observation.get("adaptation") else "observation"
                _record_step(
                    self.db,
                    self.run,
                    self._next_step_index(),
                    obs_kind,
                    tool_name=tool_name,
                    content=self._summarize_observation(tool_name, observation),
                    payload=observation,
                )

                self._history.append({
                    "index": step,
                    "tool": tool_name,
                    "args": args,
                    "observation": observation,
                })

                if observation.get("finish"):
                    break

            self._run_verifier()
            self._finalize_run(status="verified")
        except Exception as e:
            _record_step(
                self.db,
                self.run,
                self._next_step_index(),
                "observation",
                content=f"Agent crashed: {e}",
            )
            self._finalize_run(status="failed", note=str(e))
        finally:
            close_bus(self.run.id)

    def _summarize_observation(self, tool_name: str, obs: Dict[str, Any]) -> str:
        """Plain-English narration for the UI. No raw JSON in the trace body."""
        if "error" in obs:
            return f"{tool_name} error: {obs['error']}"
        if tool_name == "get_pool_stats":
            return (
                f"Pool: {obs.get('total_candidates', 0)} candidates, "
                f"{obs.get('strong_candidates', 0)} at or above the passing bar of "
                f"{obs.get('passing_threshold')}, {obs.get('unscored_candidates', 0)} not yet screened."
            )
        if tool_name == "score_unscored_candidates":
            n = obs.get('scored', 0)
            if n == 0:
                return "No new candidates needed scoring."
            top = sorted(obs.get('results', []), key=lambda r: r.get('score', 0), reverse=True)[:3]
            top_str = ", ".join(f"{t['name']} ({t['score']:.0f})" for t in top)
            return f"Scored {n} candidate{'s' if n != 1 else ''}. Top: {top_str}."
        if tool_name == "loosen_criteria":
            return (
                f"ADAPTATION — Pool was too thin at the previous bar of {obs.get('previous_threshold')}. "
                f"Lowered the passing threshold to {obs.get('new_threshold')}; "
                f"{obs.get('candidates_now_qualifying')} candidate(s) now qualify."
            )
        if tool_name == "request_more_sourcing":
            return "ADAPTATION — Flagged the pool as too thin. Queued a sourcing request for the recruiter."
        if tool_name == "send_reminder":
            return f"ADAPTATION — Sent a reminder email to {obs.get('candidate')} to complete their assessment."
        if tool_name == "regenerate_harder_questions":
            return f"ADAPTATION — Assessment scores looked inflated for {obs.get('candidate')}; generated a harder question set."
        if tool_name == "finalize_shortlist":
            sl = obs.get('shortlist', [])
            n_int = obs.get('interviews_scheduled', 0)
            if not sl:
                return "Finalized shortlist — empty. The pool couldn't produce a candidate above the bar."
            names = ", ".join(f"{c['name']} ({c['match_score']:.0f})" for c in sl)
            tail = f" Auto-scheduled {n_int} interview{'s' if n_int != 1 else ''}." if n_int else ""
            return f"Finalized shortlist ({len(sl)}): {names}.{tail}"
        if tool_name == "schedule_interview":
            return f"Scheduled interview for {obs.get('candidate')} with {obs.get('interviewer')} at {obs.get('scheduled_at','TBD')[:16].replace('T',' ')}."
        if tool_name == "generate_assessment":
            return f"Generated a {obs.get('questions_generated')}-question assessment for {obs.get('candidate_name')}."
        if tool_name == "simulate_candidate_responses":
            return f"Simulated {obs.get('quality')} response from {obs.get('candidate')} → assessment {obs.get('assessment_status')} ({obs.get('assessment_score')}/100)."
        if tool_name == "check_for_ghosted_candidates":
            n = obs.get('ghosted_count', 0)
            return "No ghosting candidates." if n == 0 else f"{n} candidate(s) are ghosting — send reminders."
        if tool_name == "finish":
            return f"Ending the run — {obs.get('reason', 'goal reached')}."
        return json.dumps(obs)[:400]

    def _run_verifier(self) -> None:
        job = self.db.query(Job).filter(Job.id == self.job_id).first()
        shortlist = self._final_shortlist
        if not shortlist:
            # Try to build one at the end anyway
            _tool_finalize_shortlist(self, {})
            shortlist = self._final_shortlist

        verdict = verify_shortlist(job.title, job.description, shortlist)
        self.run.verification_result = json.dumps(verdict)
        self.db.commit()
        _record_step(
            self.db,
            self.run,
            self._next_step_index(),
            "verification",
            content=(
                f"Independent audit: {verdict.get('verdict','?').upper()} "
                f"(confidence {verdict.get('confidence','?')}). "
                f"{verdict.get('recommendation','')}"
            ),
            payload=verdict,
        )

    def _finalize_run(self, status: str, note: str = "") -> None:
        self.run.status = status
        self.run.adaptations_count = self._adaptation_count
        self.run.tools_called = self._tool_calls
        self.run.finished_at = datetime.now(timezone.utc)
        if self._final_shortlist:
            names = ", ".join(c["name"] for c in self._final_shortlist)
            self.run.outcome_summary = (
                f"Shortlisted {len(self._final_shortlist)}: {names}. "
                f"{self._adaptation_count} adaptations, {self._tool_calls} tool calls."
            )
        else:
            self.run.outcome_summary = (
                note or f"Ended with no shortlist. Adaptations={self._adaptation_count}, tool_calls={self._tool_calls}."
            )
        self.db.commit()
        _record_step(
            self.db,
            self.run,
            self._next_step_index(),
            "final",
            content=self.run.outcome_summary,
            payload={"status": status, "shortlist": self._final_shortlist},
        )


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def start_agent_run(
    job_id: int,
    goal: str,
    company_id: Optional[int],
    target_shortlist_size: int = DEFAULT_SHORTLIST_SIZE,
    passing_threshold: float = DEFAULT_PASSING_THRESHOLD,
) -> int:
    """
    Create an AgentRun row and kick off the agent in a background thread.
    Returns the new run id immediately so the caller can subscribe to the
    SSE stream.
    """
    db = SessionLocal()
    if company_id is not None:
        current_company_id.set(company_id)
    try:
        job = db.query(Job).filter(Job.id == job_id).first()
        if not job:
            raise ValueError(f"No job with id {job_id}")

        run = AgentRun(
            job_id=job_id,
            company_id=company_id,
            goal=goal,
            status="running",
        )
        db.add(run)
        db.commit()
        db.refresh(run)
        run_id = run.id
    finally:
        db.close()

    def _worker():
        # Fresh session in the worker thread.
        worker_db = SessionLocal()
        if company_id is not None:
            current_company_id.set(company_id)
        try:
            worker_run = worker_db.query(AgentRun).filter(AgentRun.id == run_id).first()
            worker_job = worker_db.query(Job).filter(Job.id == job_id).first()
            agent = HiringAgent(
                db=worker_db,
                run=worker_run,
                job=worker_job,
                goal=goal,
                target_shortlist_size=target_shortlist_size,
                passing_threshold=passing_threshold,
            )
            agent.run_loop()
        except Exception as e:
            # Mark the run failed so the UI unblocks.
            try:
                worker_run = worker_db.query(AgentRun).filter(AgentRun.id == run_id).first()
                if worker_run:
                    worker_run.status = "failed"
                    worker_run.outcome_summary = f"Worker crashed: {e}"
                    worker_run.finished_at = datetime.now(timezone.utc)
                    worker_db.commit()
            except Exception:
                pass
        finally:
            worker_db.close()
            close_bus(run_id)

    threading.Thread(target=_worker, name=f"agent-run-{run_id}", daemon=True).start()
    return run_id
