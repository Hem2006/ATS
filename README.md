# Stitch ATS — an Agentic Hiring System

**Tech Zephyr 4.0 · IIT Bhubaneswar — Agentic AI Hackathon submission**

Stitch ATS is an autonomous hiring platform. A recruiter states a goal — e.g.
*"shortlist 3 senior React engineers for job #12"* — and a **Hiring Agent**
takes it from there: it decides what to do next, invokes the right tools,
adapts when candidates ghost or the pool is too thin, and hands back a
verified shortlist along with a full audit trail of its reasoning.

---

## 1. Problem

Hiring is the classic multi-step, high-friction workflow: parse resumes,
score them against a JD, chase candidates for assessments, regenerate
questions if they're too easy, schedule interviews, escalate stuck
candidates, and answer to a hiring manager who wants results. A recruiter
today does all of this manually across five tabs.

**Target users:** recruiters, hiring managers, delivery heads, and
technical panels at small-to-mid staffing / product companies.

## 2. Why an agent — not a workflow

A traditional pipeline is fine when every candidate follows the happy path.
The real world doesn't:

- The pool is **too thin** at the desired quality bar.
- Candidates **ghost** partway through.
- Assessment scores look **too inflated** — the questions were too easy.
- One provider (LLM, calendar, email) is **rate-limited or down**.

Each of those needs *a decision*, not a script. Stitch ATS's Hiring Agent
runs `observe → decide → act → evaluate → adapt` in a loop until the goal
is met, and it can:

1. **Choose** its next tool from a registry of 13.
2. **Adapt** by loosening thresholds, sourcing more resumes, regenerating
   harder assessments, or sending reminders — all without human input.
3. **Self-verify** its own shortlist with an independent-audit LLM pass
   before returning.
4. **Cascade** across LLM providers (Groq → OpenAI → Gemini) if one is
   down, and fall back to a deterministic rule-based policy if all are.

## 3. What it does — a concrete run

1. Recruiter clicks **Run Agent** with goal *"shortlist 3 for Senior React"*.
2. Agent calls `get_pool_stats` → observes 2 unscored candidates.
3. Calls `score_unscored_candidates` → 1 strong, 1 weak.
4. Strong pool < target of 3 → **ADAPT**: calls `loosen_criteria`, then
   `request_more_sourcing`, then re-scores.
5. For each qualified candidate → `generate_assessment`, tracks
   `assessment_pending`, calls `check_for_ghosted_candidates` after a
   simulated delay, `send_reminder` to any who lag, and — if scores look
   inflated — `regenerate_harder_questions`.
6. `finalize_shortlist` → marks the top-N candidates.
7. `schedule_interview` for each.
8. Self-verifier grades the shortlist against the JD. Verdict:
   `approved` / `revise` / `reject`, with reasons and flagged candidates.
9. Every step is streamed live to the UI as
   `THOUGHT → TOOL CALL → OBSERVATION → ADAPTATION → VERIFICATION → FINAL`.

## 4. Architecture

```
                    ┌────────────────────────────────┐
                    │        Recruiter (Web UI)      │
                    │  Agent Console — SSE stream    │
                    └───────────────┬────────────────┘
                                    │  POST /api/agent/run
                                    │  GET  /api/agent/runs/{id}/stream
                                    ▼
        ┌──────────────────────────────────────────────────────┐
        │              HiringAgent  (orchestrator)             │
        │  ─ reason → act → observe loop (max 25 steps)        │
        │  ─ repeat-guard, adaptation counter                  │
        │  ─ deterministic fallback policy if all LLMs down    │
        └──────┬───────────────────┬──────────────────┬────────┘
               │                   │                  │
               ▼                   ▼                  ▼
       ┌────────────────┐  ┌──────────────────┐  ┌──────────────┐
       │  LLM Provider  │  │   Tool Registry  │  │  Self-Verifier│
       │  chain: Groq → │  │  13 tools:       │  │  independent  │
       │  OpenAI →      │  │  score, adapt,   │  │  LLM judge    │
       │  Gemini        │  │  send, schedule…│  │               │
       └────────────────┘  └────────┬─────────┘  └───────┬──────┘
                                    │                    │
                                    ▼                    ▼
                     ┌──────────────────────────────────────────┐
                     │  Memory / State  (SQLite + SQLAlchemy)   │
                     │  jobs, candidates, screenings,           │
                     │  agent_runs, agent_steps (full trace)    │
                     └──────────────────────────────────────────┘

External systems the tools may reach: Gmail SMTP, Google Calendar,
                                       PyPDF2 / python-docx (resume parse)
```

**Failure handling** is baked in at three layers:

- **Provider chain** in `safe_chat_completion` cascades on 401/404 or
  "model not found", so one dead key never kills a run.
- **Repeat-guard** in the agent loop forces a terminal tool if the same
  tool is picked 4× in a row.
- **Deterministic fallback policy** picks the next tool by hard-coded
  phase logic (score → loosen → source → score → finalize → finish) so the
  demo never hangs if every LLM provider is down.

## 5. Repo layout

```
backend/
├── main.py                       FastAPI app + router registration
├── models.py                     SQLAlchemy models incl. AgentRun / AgentStep
├── database.py                   SQLite session + self-healing migrations
├── auth_middleware.py            multi-tenant JWT middleware
├── routers/
│   ├── agent.py                  POST /api/agent/run, SSE stream
│   ├── screening.py              JD + CV upload, screening
│   ├── assessment.py             candidate-side assessment portal
│   ├── interviews.py             scheduling + Google Calendar
│   └── ...                       dashboard, settings, auth, onboarding
└── services/
    ├── agent_orchestrator.py     HiringAgent + tool registry (THE agent)
    ├── agent_events.py           in-memory pub/sub for SSE
    ├── verifier.py               independent-audit LLM judge
    ├── ai_screening.py           JD↔CV semantic match + provider chain
    ├── assessment_eval.py        10-question test generation + grading
    ├── email_sender.py           SMTP email
    ├── google_calendar.py        Calendar integration
    └── file_parser.py            PDF / DOCX → text

frontend/
└── src/
    ├── pages/AgentConsole.jsx    Agent Console — live trace UI
    ├── pages/Screening.jsx       JD + resume upload
    ├── pages/Interviews.jsx
    └── ...                       Dashboard, Onboarding, Communications
```

## 6. Setup

### Prerequisites
- Node 18+
- Python 3.9+ (3.11 recommended)
- One of: `GROQ_API_KEY` (free), `OPENAI_API_KEY`, or `GEMINI_API_KEY`
  (free tier available). The agent tries them in that order.

### Environment

```bash
cp backend/.env.example backend/.env
# then edit backend/.env and set at least ONE LLM key
```

### Backend

```bash
python3 -m venv .venv
source .venv/bin/activate            # Windows: .venv\Scripts\activate
pip install -r backend/requirements.txt
uvicorn backend.main:app --reload --port 8001
```

### Frontend

```bash
cd frontend
npm install
npm run dev
```

Then open http://localhost:5173 and log in with a company account.

### Windows one-click

Double-click `run_windows.bat` — it creates the venv, installs deps, and
starts both servers.

## 7. Running the demo

1. Log in as a recruiter (create a company via signup if this is your
   first time; passwords are emailed if SMTP is configured, otherwise
   they're printed to the backend log).
2. Go to **AI Screening**, upload a JD, upload 3–5 CVs.
3. Open **🤖 Hiring Agent** in the sidebar.
4. Pick the job you just posted. Leave the default goal or write your own.
   Click **▶ Run Agent**.
5. Watch the trace stream in: thoughts, tool calls, observations, orange
   `ADAPTATION` cards when it changes strategy, and finally a purple
   `VERIFICATION` card with the self-audit verdict.

To deliberately trigger adaptations for the demo, upload only 1–2 strong
resumes and set the target shortlist size to 3.

## 8. Failure demo (required by the hackathon)

Two easy ways to force the agent to adapt on camera:

1. **Thin pool** — upload only 1 strong resume, set target shortlist to
   3. The agent will call `loosen_criteria`, fail to hit target,
   then `request_more_sourcing`, then re-score. Two visible adaptations.
2. **Provider outage** — temporarily invalidate the first LLM key in
   `backend/.env`. The trace will show the provider chain cascading, and
   the run will still finish.

## 9. Deployment (optional)

`render.yaml` is provided for one-click Render deployment. For local
demos, `run_windows.bat` or the two commands above are enough.

## 10. Troubleshooting

- **SSL errors on `pip install`** — add
  `--trusted-host pypi.org --trusted-host files.pythonhosted.org`.
- **`llama-*` model 404** — Groq deprecated the model your key was using.
  The provider chain cascades automatically; the run still succeeds.
- **Frontend errors after pulling changes** — delete
  `frontend/node_modules` and re-run `npm install`.
