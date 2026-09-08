"""
Stitch ATS — Investigator Router

    POST /api/investigator/run                    kick off investigation
    GET  /api/investigator/runs                   recent investigation runs
    GET  /api/investigator/runs/{id}              full run with steps
    GET  /api/investigator/runs/{id}/stream       live SSE stream
    GET  /api/investigator/candidate/{id}         latest run for a candidate
"""
from __future__ import annotations

import json
import queue

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import AgentRun, AgentStep, Candidate, User
from ..auth_utils import get_current_user
from ..services.investigator_agent import start_investigation
from ..services.agent_events import get_bus


router = APIRouter(prefix="/api/investigator", tags=["Investigator"])


class RunRequest(BaseModel):
    candidate_id: int


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
    report = None
    if run.verification_result:
        try:
            report = json.loads(run.verification_result)
        except Exception:
            report = None
    data = {
        "id": run.id,
        "run_type": run.run_type,
        "candidate_id": run.candidate_id,
        "goal": run.goal,
        "status": run.status,
        "outcome_summary": run.outcome_summary,
        "trust_report": report,
        "tools_called": run.tools_called,
        "findings_count": (report or {}).get("counts") if report else None,
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
    cand = db.query(Candidate).filter(Candidate.id == req.candidate_id).first()
    if not cand:
        raise HTTPException(status_code=404, detail=f"Candidate {req.candidate_id} not found")
    run_id = start_investigation(candidate_id=req.candidate_id, company_id=current_user.company_id)
    return {"run_id": run_id}


@router.get("/runs")
def list_runs(
    limit: int = 20,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    runs = (
        db.query(AgentRun)
        .filter(AgentRun.run_type == "investigation")
        .order_by(AgentRun.id.desc())
        .limit(limit)
        .all()
    )
    return [_serialize_run(r, include_steps=False) for r in runs]


@router.get("/runs/{run_id}")
def get_run(run_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    run = db.query(AgentRun).filter(AgentRun.id == run_id).first()
    if not run:
        raise HTTPException(status_code=404, detail=f"Run {run_id} not found")
    return _serialize_run(run, include_steps=True)


@router.get("/candidate/{candidate_id}")
def latest_for_candidate(
    candidate_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    run = (
        db.query(AgentRun)
        .filter(AgentRun.candidate_id == candidate_id)
        .filter(AgentRun.run_type == "investigation")
        .order_by(AgentRun.id.desc())
        .first()
    )
    if not run:
        return None
    return _serialize_run(run, include_steps=True)


@router.get("/runs/{run_id}/stream")
def stream_run(run_id: int, request: Request, db: Session = Depends(get_db)):
    """SSE mirror of the /api/agent/runs/{id}/stream endpoint but for investigations."""
    run = db.query(AgentRun).filter(AgentRun.id == run_id).first()
    if not run:
        raise HTTPException(status_code=404, detail=f"Run {run_id} not found")

    bus = get_bus(run_id)
    subscription = bus.subscribe()
    existing = list(run.steps)
    terminal_status = run.status

    def event_gen():
        for s in existing:
            yield f"event: step\ndata: {json.dumps(_serialize_step(s))}\n\n"
        if terminal_status in ("verified", "completed", "failed"):
            yield f"event: done\ndata: {json.dumps({'status': terminal_status})}\n\n"
            return
        while True:
            try:
                event = subscription.get(timeout=15)
            except queue.Empty:
                yield ": keep-alive\n\n"
                continue
            if event is None:
                yield f"event: done\ndata: {json.dumps({'status': 'ended'})}\n\n"
                break
            yield f"event: step\ndata: {json.dumps(event)}\n\n"

    return StreamingResponse(
        event_gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no", "Connection": "keep-alive"},
    )
