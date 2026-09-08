"""
Stitch ATS — Hiring Agent Router
Endpoints for starting, watching, and inspecting autonomous agent runs.

    POST   /api/agent/run                  Kick off a new run, return run_id
    GET    /api/agent/runs                 List recent runs
    GET    /api/agent/runs/{run_id}        Full run with all steps
    GET    /api/agent/runs/{run_id}/stream Live SSE stream of steps
"""
from __future__ import annotations

import json
import queue
import time
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import AgentRun, AgentStep, Job, User
from ..auth_utils import get_current_user
from ..services.agent_orchestrator import (
    start_agent_run,
    DEFAULT_SHORTLIST_SIZE,
    DEFAULT_PASSING_THRESHOLD,
)
from ..services.agent_events import get_bus

router = APIRouter(prefix="/api/agent", tags=["Agent"])


class RunRequest(BaseModel):
    job_id: int
    goal: Optional[str] = None
    target_shortlist_size: int = DEFAULT_SHORTLIST_SIZE
    passing_threshold: float = DEFAULT_PASSING_THRESHOLD


def _serialize_step(step: AgentStep) -> dict:
    payload = None
    if step.payload:
        try:
            payload = json.loads(step.payload)
        except Exception:
            payload = step.payload
    return {
        "id": step.id,
        "run_id": step.run_id,
        "step_index": step.step_index,
        "kind": step.kind,
        "tool_name": step.tool_name,
        "content": step.content,
        "payload": payload,
        "created_at": step.created_at.isoformat() if step.created_at else None,
    }


def _serialize_run(run: AgentRun, include_steps: bool = False) -> dict:
    verification = None
    if run.verification_result:
        try:
            verification = json.loads(run.verification_result)
        except Exception:
            verification = run.verification_result
    data = {
        "id": run.id,
        "job_id": run.job_id,
        "goal": run.goal,
        "status": run.status,
        "outcome_summary": run.outcome_summary,
        "verification": verification,
        "adaptations_count": run.adaptations_count,
        "tools_called": run.tools_called,
        "started_at": run.started_at.isoformat() if run.started_at else None,
        "finished_at": run.finished_at.isoformat() if run.finished_at else None,
    }
    if include_steps:
        data["steps"] = [_serialize_step(s) for s in run.steps]
    return data


@router.post("/run")
def create_run(
    req: RunRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    job = db.query(Job).filter(Job.id == req.job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail=f"Job {req.job_id} not found")

    goal = req.goal or (
        f"Shortlist {req.target_shortlist_size} qualified candidates "
        f"for '{job.title}' with match score >= {req.passing_threshold}."
    )
    run_id = start_agent_run(
        job_id=req.job_id,
        goal=goal,
        company_id=current_user.company_id,
        target_shortlist_size=req.target_shortlist_size,
        passing_threshold=req.passing_threshold,
    )
    return {"run_id": run_id, "goal": goal}


@router.get("/runs")
def list_runs(
    limit: int = 20,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    runs = db.query(AgentRun).order_by(AgentRun.id.desc()).limit(limit).all()
    return [_serialize_run(r, include_steps=False) for r in runs]


@router.get("/runs/{run_id}")
def get_run(
    run_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    run = db.query(AgentRun).filter(AgentRun.id == run_id).first()
    if not run:
        raise HTTPException(status_code=404, detail=f"Run {run_id} not found")
    return _serialize_run(run, include_steps=True)


@router.get("/runs/{run_id}/stream")
def stream_run(run_id: int, request: Request, db: Session = Depends(get_db)):
    """
    Live SSE stream. Emits any steps already persisted first, then follows
    new events published on the run's event bus until the run ends or
    the client disconnects.

    Note: SSE deliberately does not require a bearer token in the URL — most
    EventSource clients can't set headers. Restrict access at your gateway.
    """
    run = db.query(AgentRun).filter(AgentRun.id == run_id).first()
    if not run:
        raise HTTPException(status_code=404, detail=f"Run {run_id} not found")

    bus = get_bus(run_id)
    subscription = bus.subscribe()
    # Capture existing steps BEFORE we start streaming so we don't miss any.
    existing = list(run.steps)
    terminal_run_status = run.status

    def event_gen():
        # 1) replay history so a late-joining client still sees the full trace
        for s in existing:
            yield f"event: step\ndata: {json.dumps(_serialize_step(s))}\n\n"
        # If the run already ended, emit a done event and exit
        if terminal_run_status in ("verified", "completed", "failed"):
            yield f"event: done\ndata: {json.dumps({'status': terminal_run_status})}\n\n"
            return

        # 2) stream live events
        while True:
            try:
                event = subscription.get(timeout=15)
            except queue.Empty:
                # keep-alive comment so proxies don't drop the connection
                yield ": keep-alive\n\n"
                continue
            if event is None:
                # bus closed → run finished
                yield f"event: done\ndata: {json.dumps({'status': 'ended'})}\n\n"
                break
            yield f"event: step\ndata: {json.dumps(event)}\n\n"

    return StreamingResponse(
        event_gen(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )
