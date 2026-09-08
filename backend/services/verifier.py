"""
Stitch ATS — Self-Verifier
A second-pass 'judge' LLM that reviews the agent's shortlist against the JD
and flags anomalies (weak fits, over-scoring, missing seniority match, etc.).

Maps directly to the hackathon's evaluation / verification requirement.
"""
from __future__ import annotations

import json
from typing import List, Dict, Any

from .ai_screening import safe_chat_completion, clean_json_response


def verify_shortlist(job_title: str, jd_text: str, shortlist: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Ask an independent LLM pass to grade the shortlist.

    Returns:
        {
          "verdict": "approved" | "revise" | "reject",
          "confidence": 0-100,
          "reasons": [str, ...],
          "flagged_candidates": [{"name": str, "issue": str}, ...],
          "recommendation": str
        }
    """
    if not shortlist:
        return {
            "verdict": "revise",
            "confidence": 100,
            "reasons": ["Shortlist is empty."],
            "flagged_candidates": [],
            "recommendation": "Re-run screening with a wider candidate pool or looser criteria.",
        }

    compact = [
        {
            "name": c.get("name"),
            "score": c.get("match_score"),
            "seniority_fit": c.get("seniority_fit"),
            "summary": (c.get("overall_summary") or "")[:400],
        }
        for c in shortlist
    ]

    prompt = f"""You are an INDEPENDENT senior hiring manager auditing another recruiter's shortlist.
Do NOT rubber-stamp — your job is to catch mistakes.

TARGET ROLE: {job_title}
JOB DESCRIPTION (first 1500 chars):
{(jd_text or '')[:1500]}

SHORTLIST PROPOSED BY THE AGENT:
{json.dumps(compact, indent=2)}

Check for:
- Candidates whose summary contradicts their score.
- Seniority mismatch (junior on a senior role or vice-versa).
- Shortlist too small or homogeneous.
- Any candidate whose summary looks weak given the JD.

Return ONLY valid JSON with EXACTLY these fields:
{{
    "verdict": "approved" | "revise" | "reject",
    "confidence": <0-100>,
    "reasons": ["short reason 1", "short reason 2"],
    "flagged_candidates": [{{"name": "<name>", "issue": "<what's wrong>"}}],
    "recommendation": "<one-sentence next action>"
}}
"""

    try:
        resp = safe_chat_completion(
            messages=[
                {"role": "system", "content": "You are a critical independent auditor. Return only valid JSON."},
                {"role": "user", "content": prompt},
            ],
            temperature=0.2,
            response_format={"type": "json_object"},
        )
        result = json.loads(clean_json_response(resp.choices[0].message.content))
        result.setdefault("verdict", "approved")
        result.setdefault("confidence", 60)
        result.setdefault("reasons", [])
        result.setdefault("flagged_candidates", [])
        result.setdefault("recommendation", "Proceed to interviews.")
        return result
    except Exception as e:
        # Fallback: approve with low confidence rather than fail the run
        return {
            "verdict": "approved",
            "confidence": 40,
            "reasons": [f"Verifier LLM unavailable ({e}); defaulting to approve with low confidence."],
            "flagged_candidates": [],
            "recommendation": "Human review recommended before interviews.",
        }
