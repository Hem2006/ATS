"""
Stitch ATS — Investigator Agent

A truly agentic loop: given ONE candidate, the agent conducts a
multi-step investigation to produce a Trust Report. The sequence of
tools it calls is NOT scripted — it depends on what evidence it finds
along the way (missing GitHub → different path than empty GitHub, etc).

Tools:
  fetch_github_profile(username?)        # username inferred if omitted
  list_github_repos()                    # requires profile fetched
  read_repo_readme(full_name, branch?)   # deep-dive on one repo
  ai_detect(text, label)                 # is this text AI-generated?
  consistency_check(cv_claim, evidence)  # LLM-as-judge on one claim
  flag_finding(severity, category, note) # accumulate report entries
  finalize_verdict(trust_score, summary) # terminal

Output: `verification_result` on the AgentRun holds the structured Trust
Report. `outcome_summary` holds the one-line human summary.
"""
from __future__ import annotations

import json
import re
import threading
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from ..database import SessionLocal
from ..tenant import current_company_id
from ..models import AgentRun, AgentStep, Candidate
from .agent_events import get_bus, close_bus
from .ai_screening import safe_chat_completion, clean_json_response
from . import github_client as gh


MAX_STEPS = 14


# ---------------------------------------------------------------------------
# Persisted step helpers (identical semantics to the hiring agent)
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
    get_bus(run.id).publish({
        "id": step.id, "run_id": run.id, "step_index": step_index,
        "kind": kind, "tool_name": tool_name, "content": content, "payload": payload,
        "created_at": step.created_at.isoformat() if step.created_at else None,
    })
    return step


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------

def _tool_fetch_github_profile(agent: "InvestigatorAgent", args: Dict[str, Any]) -> Dict[str, Any]:
    """
    Resolve a username (from args or from the candidate's stored URL) and
    fetch the profile. Stashes profile on the agent for later tools.
    """
    username = args.get("username") or gh.extract_username(agent.candidate.github_url) \
                                     or gh.extract_username(_guess_github_from_cv(agent.candidate.resume_text or ""))
    if not username:
        return {
            "error": "no_github_reference",
            "note": "No GitHub URL on file and none detectable in the resume text.",
        }
    profile = gh.fetch_profile(username)
    if "error" in profile:
        return {"username": username, **profile}
    agent._gh_profile = profile
    agent._gh_username = username
    return profile


def _tool_list_github_repos(agent: "InvestigatorAgent", args: Dict[str, Any]) -> Dict[str, Any]:
    if not agent._gh_username:
        return {"error": "call_fetch_github_profile_first"}
    repos = gh.fetch_repos(agent._gh_username, limit=int(args.get("limit", 30)))
    agent._gh_repos = repos
    summary = gh.summarize_repos(repos)
    return {
        "count": len(repos),
        "summary": summary,
        # Only give the model a compact list to save tokens
        "repos": [
            {
                "full_name": r["full_name"],
                "language":  r["language"],
                "stars":     r["stars"],
                "pushed_at": r["pushed_at"],
                "description": (r["description"] or "")[:120],
            }
            for r in repos[:15]
        ],
    }


def _tool_read_repo_readme(agent: "InvestigatorAgent", args: Dict[str, Any]) -> Dict[str, Any]:
    full_name = args.get("full_name")
    branch = args.get("branch") or "main"
    if not full_name:
        return {"error": "full_name required (e.g. 'user/repo')"}
    return gh.fetch_readme(full_name, branch=branch)


def _tool_ai_detect(agent: "InvestigatorAgent", args: Dict[str, Any]) -> Dict[str, Any]:
    """
    LLM-as-judge for AI-generated text. Returns a 0-100 likelihood plus
    the human-readable signals that drove the score.
    """
    text = (args.get("text") or "").strip()
    label = args.get("label") or "text"
    if not text:
        return {"error": "no_text_provided"}
    if len(text) < 60:
        return {"label": label, "ai_likelihood": 0, "confidence": "low",
                "note": "Too short to judge (<60 chars)."}

    prompt = f"""You are an expert at spotting LLM-generated writing.

Analyze the {label} below. Rate 0-100 the likelihood it was generated by an
AI model (ChatGPT, Claude, Gemini, etc.), NOT the quality. Consider:
- Overuse of hedges and clichés ("in today's fast-paced world", "leveraging synergies")
- Uniformly polished sentences, no personal specifics
- Lack of concrete numbers, project names, or first-person memory
- "Corporate polish" without real content
- Templated bullet-point structure

Return JSON exactly:
{{
  "ai_likelihood": <0-100>,
  "confidence":   "low" | "medium" | "high",
  "signals":      ["signal 1", "signal 2", "signal 3"]
}}

TEXT ({label}):
\"\"\"{text[:2000]}\"\"\"
"""
    try:
        r = safe_chat_completion(
            messages=[
                {"role": "system", "content": "Return only valid JSON."},
                {"role": "user", "content": prompt},
            ],
            temperature=0.2,
            response_format={"type": "json_object"},
        )
        result = json.loads(clean_json_response(r.choices[0].message.content))
        result["label"] = label
        return result
    except Exception as e:
        return {"error": f"llm_failed: {e}", "label": label}


def _tool_consistency_check(agent: "InvestigatorAgent", args: Dict[str, Any]) -> Dict[str, Any]:
    """
    Compare a specific CV claim against a specific piece of evidence.
    Returns verified / partially_verified / contradicted / unverifiable
    with a short reason.
    """
    claim = (args.get("cv_claim") or "").strip()
    evidence = (args.get("evidence") or "").strip()
    if not claim:
        return {"error": "cv_claim required"}
    if not evidence:
        return {"error": "evidence required"}

    prompt = f"""You are auditing a resume claim against public evidence.

CV CLAIM:
{claim[:800]}

EVIDENCE (public data, e.g. GitHub profile / repo README / repo list):
{evidence[:2500]}

Judge whether the evidence supports the claim. Return JSON exactly:
{{
  "verdict": "verified" | "partially_verified" | "contradicted" | "unverifiable",
  "confidence": <0-100>,
  "reason": "<one short sentence>"
}}
Be strict — a claim of '10 years Python at scale' is NOT verified by 3 boilerplate repos.
"""
    try:
        r = safe_chat_completion(
            messages=[
                {"role": "system", "content": "Return only valid JSON."},
                {"role": "user", "content": prompt},
            ],
            temperature=0.2,
            response_format={"type": "json_object"},
        )
        return json.loads(clean_json_response(r.choices[0].message.content))
    except Exception as e:
        return {"error": f"llm_failed: {e}", "claim": claim[:120]}


def _tool_flag_finding(agent: "InvestigatorAgent", args: Dict[str, Any]) -> Dict[str, Any]:
    """Append a structured finding to the internal report."""
    finding = {
        "severity":  args.get("severity", "info"),   # info | low | medium | high | critical
        "category":  args.get("category", "general"),
        "note":      (args.get("note") or "").strip(),
        "evidence":  (args.get("evidence") or "").strip()[:400],
    }
    if not finding["note"]:
        return {"error": "note is required"}
    agent._findings.append(finding)
    return {"flagged": True, "total_findings": len(agent._findings), "finding": finding}


def _tool_finalize_verdict(agent: "InvestigatorAgent", args: Dict[str, Any]) -> Dict[str, Any]:
    """
    Terminal tool. Compose the trust report from accumulated findings
    plus the LLM's suggested score/summary.
    """
    try:
        score = float(args.get("trust_score", 50))
    except Exception:
        score = 50.0
    score = max(0.0, min(100.0, score))

    summary = (args.get("summary") or "").strip() or "Investigation complete."
    tier = ("high_risk" if score < 40
            else "caution" if score < 65
            else "moderate_trust" if score < 80
            else "high_trust")

    counts = {"critical": 0, "high": 0, "medium": 0, "low": 0, "info": 0}
    for f in agent._findings:
        s = f.get("severity", "info")
        if s in counts:
            counts[s] += 1

    report = {
        "candidate_id":   agent.candidate.id,
        "candidate_name": agent.candidate.name,
        "trust_score":    score,
        "tier":           tier,
        "summary":        summary,
        "findings":       agent._findings,
        "counts":         counts,
        "sources": {
            "github_username": agent._gh_username,
            "github_repos_seen": len(agent._gh_repos or []),
        },
    }
    agent._verdict = report
    return {"finish": True, "report": report}


TOOL_REGISTRY: Dict[str, Dict[str, Any]] = {
    "fetch_github_profile": {
        "fn": _tool_fetch_github_profile,
        "description": "Fetch the candidate's GitHub profile. Uses the stored URL by default; pass {username:'...'} to override. Returns bio, public repo count, followers, account age.",
    },
    "list_github_repos": {
        "fn": _tool_list_github_repos,
        "description": "List the candidate's non-fork repos with language, stars, and last-push date. Call after fetch_github_profile. Returns a compact summary.",
    },
    "read_repo_readme": {
        "fn": _tool_read_repo_readme,
        "description": "Read one repo's README to see if it matches a specific CV claim. Args: {full_name:'user/repo', branch:'main'?}.",
    },
    "ai_detect": {
        "fn": _tool_ai_detect,
        "description": "Judge whether a piece of text is AI-generated. Args: {text:'...', label:'cover_letter'|'assessment_answer'|'summary'}. Returns ai_likelihood 0-100.",
    },
    "consistency_check": {
        "fn": _tool_consistency_check,
        "description": "Compare one CV claim against one piece of evidence. Args: {cv_claim:'...', evidence:'...'}. Returns verified/partially_verified/contradicted/unverifiable.",
    },
    "flag_finding": {
        "fn": _tool_flag_finding,
        "description": "Record a finding in the trust report. Args: {severity:'critical'|'high'|'medium'|'low'|'info', category:'inflation'|'ai_generated'|'positive_signal'|..., note:'human-readable', evidence:'...'}.",
    },
    "finalize_verdict": {
        "fn": _tool_finalize_verdict,
        "description": "TERMINAL. Args: {trust_score:0-100, summary:'one paragraph'}. Ends the run.",
    },
}


# ---------------------------------------------------------------------------
# Guessing a GitHub URL from raw resume text as a fallback
# ---------------------------------------------------------------------------

def _guess_github_from_cv(text: str) -> Optional[str]:
    if not text:
        return None
    m = re.search(r"(?:https?://)?(?:www\.)?github\.com/[A-Za-z0-9-]+", text, re.IGNORECASE)
    return m.group(0) if m else None


# ---------------------------------------------------------------------------
# The agent
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """You are an autonomous Candidate Investigator.

Given ONE candidate you must produce a TRUST REPORT: a 0-100 trust score
plus specific findings. The sequence of steps is NOT fixed — it depends on
what evidence you find.

Reply with EXACTLY one JSON object per step:

{
  "thought": "<one short sentence explaining WHY this move>",
  "tool":    "<tool from the registry>",
  "args":    { ... }
}

Return ONLY that JSON. No markdown. No prose outside the JSON.

INVESTIGATION APPROACH (adapt as you learn):
  1. Try fetch_github_profile — this anchors most tech investigations.
  2. If found: list_github_repos, then reason about whether the repo pattern
     matches the seniority/tech claimed in the CV. Read a specific README
     (via read_repo_readme) ONLY if a CV claim points at that project by name.
  3. If a specific CV claim is worth challenging (e.g. "5 years Python at
     scale"), call consistency_check with the claim + the repo summary.
  4. If assessment_responses or a cover_letter is available, call ai_detect
     on it — a high AI-likelihood score is a red flag worth recording.
  5. Whenever you have concrete evidence — good OR bad — call flag_finding.
     Categories: 'inflation', 'ai_generated', 'unverified_claim',
     'positive_signal', 'timeline_mismatch', 'missing_evidence'.
  6. After 3-6 tool calls (never more than 10), call finalize_verdict with
     a trust score and a one-paragraph summary. Ground the score in the
     findings — don't invent numbers.

SCORING GUIDE:
  90-100 = high_trust      (multiple strong verifications)
  70-89  = moderate_trust  (mostly consistent, minor gaps)
  40-69  = caution         (mixed signals, some inflation)
  0-39   = high_risk       (contradictions, AI-generated answers, etc.)

An absence of GitHub is NOT automatically a red flag — some roles don't need
one. Score based on what the CV CLAIMS vs what evidence supports.

Never repeat a tool call that returned an error twice in a row.
"""


class InvestigatorAgent:
    def __init__(self, db: Session, run: AgentRun, candidate: Candidate):
        self.db = db
        self.run = run
        self.candidate = candidate
        self._history: List[Dict[str, Any]] = []
        self._step_index = 0
        self._findings: List[Dict[str, Any]] = []
        self._verdict: Optional[Dict[str, Any]] = None
        self._tool_calls = 0
        self._gh_profile: Optional[Dict[str, Any]] = None
        self._gh_username: Optional[str] = None
        self._gh_repos: Optional[List[Dict[str, Any]]] = None

    def _next_step_index(self) -> int:
        self._step_index += 1
        return self._step_index

    def _tool_catalog(self) -> str:
        return "\n".join(f"- {n}: {spec['description']}" for n, spec in TOOL_REGISTRY.items())

    def _dossier(self) -> str:
        """The initial context blob the LLM sees on every step."""
        c = self.candidate
        try:
            assessment = json.loads(c.assessment_responses) if c.assessment_responses else None
        except Exception:
            assessment = None

        # A short trimmed CV so the LLM can cite specific claims
        cv = (c.resume_text or "")[:2200]

        # Pull an assessment answer sample if present
        answer_sample = ""
        if assessment and isinstance(assessment, dict):
            ans = assessment.get("answers") or []
            if ans and isinstance(ans, list):
                answer_sample = str(ans[0])[:600]

        return (
            f"CANDIDATE: {c.name}  (id={c.id})\n"
            f"CLAIMED ROLE: {c.role or '(none)'}\n"
            f"STORED GITHUB URL: {c.github_url or '(none)'}\n"
            f"STORED LINKEDIN URL: {c.linkedin_url or '(none)'}\n"
            f"RESUME EXCERPT:\n{cv}\n\n"
            + (f"FIRST ASSESSMENT ANSWER:\n{answer_sample}\n" if answer_sample else "")
        )

    def _ask_next_action(self) -> Dict[str, Any]:
        history_lines = []
        for h in self._history[-8:]:
            history_lines.append(
                f"STEP {h['index']} — tool={h['tool']} args={json.dumps(h['args'])[:200]} "
                f"observation={json.dumps(h['observation'])[:400]}"
            )
        history_text = "\n".join(history_lines) if history_lines else "(none yet)"

        prompt = f"""{self._dossier()}

FINDINGS SO FAR ({len(self._findings)}):
{json.dumps(self._findings[-6:], indent=2) if self._findings else '(none)'}

TOOLS:
{self._tool_catalog()}

HISTORY (last 8 steps):
{history_text}

Choose your next action as JSON. Return JSON ONLY.
"""
        try:
            r = safe_chat_completion(
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.3,
                response_format={"type": "json_object"},
            )
            parsed = json.loads(clean_json_response(r.choices[0].message.content))
            if not isinstance(parsed, dict) or "tool" not in parsed:
                raise ValueError(f"malformed: {parsed!r}")
            parsed.setdefault("thought", "")
            parsed.setdefault("args", {})
            if not isinstance(parsed["args"], dict):
                parsed["args"] = {}
            return parsed
        except Exception as e:
            return self._fallback_action(str(e))

    def _fallback_action(self, error: str) -> Dict[str, Any]:
        """Deterministic backup if the LLM is unreachable."""
        def pick(tool, thought, args=None):
            return {"thought": thought, "tool": tool, "args": args or {}}
        if not self._history:
            return pick("fetch_github_profile", f"LLM unavailable ({error[:60]}); start with GitHub.")
        if self._gh_profile is None and self._gh_username is None:
            return pick("flag_finding", "Fallback: note missing GitHub reference.",
                        {"severity": "medium", "category": "missing_evidence",
                         "note": "Could not resolve any GitHub profile for the candidate."})
        if self._gh_username and self._gh_repos is None:
            return pick("list_github_repos", "Fallback: pull repo list.")
        if not self._verdict:
            return pick("finalize_verdict", "Fallback: wrap up with a neutral verdict.",
                        {"trust_score": 55, "summary": "Investigation ended with limited evidence."})
        return pick("finalize_verdict", "Fallback: done.",
                    {"trust_score": self._verdict.get("trust_score", 55),
                     "summary": self._verdict.get("summary", "done")})

    def _summarize(self, tool_name: str, obs: Dict[str, Any]) -> str:
        """Plain-English narration for the UI."""
        if "error" in obs and tool_name != "fetch_github_profile":
            return f"{tool_name} → {obs['error']}"

        if tool_name == "fetch_github_profile":
            if obs.get("error") == "not_found":
                return f"GitHub user '{obs.get('username')}' not found — profile does not exist."
            if obs.get("error") == "no_github_reference":
                return "No GitHub URL on file for this candidate."
            if "error" in obs:
                return f"GitHub API error: {obs['error']}"
            return (
                f"Found GitHub: @{obs.get('username')} · "
                f"{obs.get('public_repos', 0)} public repos · "
                f"{obs.get('followers', 0)} followers · "
                f"joined {(obs.get('created_at') or '')[:10]}."
            )
        if tool_name == "list_github_repos":
            s = obs.get("summary") or {}
            langs = ", ".join(f"{k}×{v}" for k, v in list((s.get('languages') or {}).items())[:4])
            return (
                f"{obs.get('count', 0)} own repos · languages: {langs or '(none)'} · "
                f"{s.get('total_stars', 0)} stars total · "
                f"newest push {(s.get('newest') or '')[:10] or 'unknown'}."
            )
        if tool_name == "read_repo_readme":
            if "error" in obs:
                return f"Could not read README for {obs.get('full_name')}."
            return f"Read README ({len(obs.get('content', ''))} chars) from {obs.get('source', '?')}."
        if tool_name == "ai_detect":
            if "error" in obs:
                return f"AI-detect skipped: {obs['error']}"
            lik = obs.get("ai_likelihood", 0)
            tag = "🚩 HIGH" if lik >= 75 else "⚠️ SUSPECT" if lik >= 45 else "✅ human-like"
            return f"AI-likelihood on {obs.get('label')}: {lik}/100 {tag}. Signals: {', '.join(obs.get('signals', []))[:200]}"
        if tool_name == "consistency_check":
            if "error" in obs:
                return f"Consistency check failed: {obs['error']}"
            return f"Claim → {obs.get('verdict', '?').upper()} (conf {obs.get('confidence','?')}). {obs.get('reason','')}"
        if tool_name == "flag_finding":
            f = obs.get("finding") or {}
            return f"FLAG [{f.get('severity','?').upper()}] {f.get('category','')}: {f.get('note','')}"
        if tool_name == "finalize_verdict":
            r = obs.get("report") or {}
            return (
                f"Verdict: {r.get('trust_score',0):.0f}/100 · {r.get('tier','?').replace('_',' ')}. "
                f"{r.get('summary','')[:300]}"
            )
        return json.dumps(obs)[:400]

    def run_loop(self) -> None:
        try:
            _record_step(
                self.db, self.run, self._next_step_index(), "thought",
                content=f"Investigating {self.candidate.name}. Building trust report.",
                payload={"candidate_id": self.candidate.id},
            )

            same_tool_streak = 0
            last_tool = None
            for step in range(MAX_STEPS):
                action = self._ask_next_action()
                thought = action.get("thought", "")
                tool_name = action.get("tool")
                args = action.get("args", {})

                if tool_name == last_tool:
                    same_tool_streak += 1
                else:
                    same_tool_streak = 0
                last_tool = tool_name
                if same_tool_streak >= 3:
                    _record_step(
                        self.db, self.run, self._next_step_index(), "thought",
                        content=f"Repeat-guard: '{tool_name}' picked 4x — forcing verdict.",
                    )
                    tool_name = "finalize_verdict"
                    args = {"trust_score": 55, "summary": "Concluded early due to repeat-guard."}
                    same_tool_streak = 0
                    last_tool = tool_name

                _record_step(
                    self.db, self.run, self._next_step_index(), "thought", content=thought,
                )

                if tool_name not in TOOL_REGISTRY:
                    _record_step(
                        self.db, self.run, self._next_step_index(), "observation",
                        tool_name=tool_name,
                        content=f"Unknown tool '{tool_name}'. Skipping.",
                    )
                    continue

                _record_step(
                    self.db, self.run, self._next_step_index(), "tool_call",
                    tool_name=tool_name, content=f"Calling {tool_name}", payload=args,
                )

                try:
                    observation = TOOL_REGISTRY[tool_name]["fn"](self, args)
                except Exception as tool_error:
                    observation = {"error": f"Tool raised: {tool_error}"}

                self._tool_calls += 1

                _record_step(
                    self.db, self.run, self._next_step_index(),
                    "adaptation" if tool_name == "flag_finding" and (observation.get("finding") or {}).get("severity") in ("high", "critical")
                    else "observation",
                    tool_name=tool_name,
                    content=self._summarize(tool_name, observation),
                    payload=observation,
                )

                self._history.append({
                    "index": step, "tool": tool_name, "args": args, "observation": observation,
                })

                if observation.get("finish"):
                    break

            self._finalize_run(status="verified")
        except Exception as e:
            _record_step(
                self.db, self.run, self._next_step_index(), "observation",
                content=f"Agent crashed: {e}",
            )
            self._finalize_run(status="failed", note=str(e))
        finally:
            close_bus(self.run.id)

    def _extract_profile(self) -> Dict[str, Any]:
        """
        One-shot structured extraction of the candidate's career from the resume
        so the frontend dossier has real content (companies, projects, education).
        Best-effort — degrades to an empty skeleton on failure.
        """
        cv = (self.candidate.resume_text or "")[:4000]
        if not cv.strip():
            return {"headline": None, "location": None, "companies": [], "projects": [], "education": [], "skills": []}

        prompt = f"""Extract a candidate's career profile from the resume below.
Return ONLY valid JSON matching this exact shape (all fields required, use empty
arrays / null when not present):

{{
  "headline":   "<one-line current title / positioning, or null>",
  "location":   "<city, country, or null>",
  "companies":  [
    {{ "name": "<company>", "role": "<title>", "dates": "<e.g. 2020-2023 or 3 yrs>",
       "highlights": ["<short bullet>", "..."] }}
  ],
  "projects":   [
    {{ "name": "<project>", "description": "<one sentence>", "tech": ["<tag>", "..."] }}
  ],
  "education":  [
    {{ "school": "<name>", "degree": "<name>", "year": "<year or range>" }}
  ],
  "skills":     ["<skill>", "..."]
}}

Rules:
- Order companies most-recent first.
- Keep highlights to 5 words each, max 3 per company.
- Skills: max 10, deduplicated.
- If the resume is thin, return whatever is present — do NOT invent.

RESUME:
{cv}
"""
        try:
            r = safe_chat_completion(
                messages=[
                    {"role": "system", "content": "Return only valid JSON. No commentary."},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.1,
                response_format={"type": "json_object"},
            )
            data = json.loads(clean_json_response(r.choices[0].message.content))
            # Defensive defaults
            for k, default in [("headline", None), ("location", None),
                               ("companies", []), ("projects", []),
                               ("education", []), ("skills", [])]:
                data.setdefault(k, default)
            return data
        except Exception as e:
            return {"headline": None, "location": None,
                    "companies": [], "projects": [], "education": [], "skills": [],
                    "extract_error": str(e)[:200]}

    def _finalize_run(self, status: str, note: str = "") -> None:
        # Ensure we always have a report — even if the LLM never called finalize.
        if self._verdict is None:
            # Compute a heuristic score from findings so the UI has something.
            weights = {"critical": -30, "high": -18, "medium": -8, "low": -3, "info": 1, "positive_signal": 4}
            score = 65
            for f in self._findings:
                score += weights.get(f.get("severity", "info"), 0)
            score = max(0, min(100, score))
            self._verdict = {
                "candidate_id": self.candidate.id,
                "candidate_name": self.candidate.name,
                "trust_score": score,
                "tier": "caution" if score < 65 else "moderate_trust",
                "summary": note or "Investigation ended before the agent finalized. Score derived from accumulated findings.",
                "findings": self._findings,
                "counts": {"critical": 0, "high": 0, "medium": 0, "low": 0, "info": len(self._findings)},
                "sources": {"github_username": self._gh_username, "github_repos_seen": len(self._gh_repos or [])},
            }

        # Attach a structured career profile so the frontend dossier can
        # show companies, projects, education without re-parsing on the client.
        if "profile" not in self._verdict:
            self._verdict["profile"] = self._extract_profile()

        # Include the raw stored fields the UI wants alongside investigation
        # output so the dossier is self-contained.
        self._verdict["candidate"] = {
            "id":         self.candidate.id,
            "name":       self.candidate.name,
            "email":      self.candidate.email,
            "role":       self.candidate.role,
            "github_url": self.candidate.github_url,
            "linkedin_url": self.candidate.linkedin_url,
        }

        self.run.status = status
        self.run.tools_called = self._tool_calls
        self.run.adaptations_count = sum(
            1 for f in self._findings if f.get("severity") in ("high", "critical")
        )
        self.run.verification_result = json.dumps(self._verdict)
        self.run.outcome_summary = (
            f"Trust score {self._verdict['trust_score']:.0f}/100 · "
            f"{self._verdict['tier'].replace('_',' ')} · "
            f"{len(self._findings)} findings"
        )
        self.run.finished_at = datetime.now(timezone.utc)
        self.db.commit()

        _record_step(
            self.db, self.run, self._next_step_index(), "final",
            content=self.run.outcome_summary,
            payload={"status": status, "report": self._verdict},
        )


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def start_investigation(candidate_id: int, company_id: Optional[int]) -> int:
    """Create the AgentRun row and kick off the agent in a worker thread."""
    db = SessionLocal()
    if company_id is not None:
        current_company_id.set(company_id)
    try:
        candidate = db.query(Candidate).filter(Candidate.id == candidate_id).first()
        if not candidate:
            raise ValueError(f"No candidate with id {candidate_id}")

        run = AgentRun(
            candidate_id=candidate_id,
            company_id=company_id,
            run_type="investigation",
            goal=f"Investigate candidate #{candidate_id} ({candidate.name}) and produce a trust report.",
            status="running",
        )
        db.add(run); db.commit(); db.refresh(run)
        run_id = run.id
    finally:
        db.close()

    def _worker():
        worker_db = SessionLocal()
        if company_id is not None:
            current_company_id.set(company_id)
        try:
            worker_run = worker_db.query(AgentRun).filter(AgentRun.id == run_id).first()
            worker_cand = worker_db.query(Candidate).filter(Candidate.id == candidate_id).first()
            InvestigatorAgent(worker_db, worker_run, worker_cand).run_loop()
        except Exception as e:
            try:
                r = worker_db.query(AgentRun).filter(AgentRun.id == run_id).first()
                if r:
                    r.status = "failed"
                    r.outcome_summary = f"Worker crashed: {e}"
                    r.finished_at = datetime.now(timezone.utc)
                    worker_db.commit()
            except Exception:
                pass
        finally:
            worker_db.close()
            close_bus(run_id)

    threading.Thread(target=_worker, name=f"investigator-{run_id}", daemon=True).start()
    return run_id
