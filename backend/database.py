"""
Stitch ATS — Database Configuration
SQLite + SQLAlchemy async-compatible setup
"""

from pathlib import Path
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base

import os

_db_path = Path(__file__).resolve().parent / "stitch_ats.db"
DATABASE_URL = os.getenv("DATABASE_URL", f"sqlite:///{_db_path.as_posix()}")

engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def get_db():
    """Dependency for FastAPI routes — yields a DB session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    """Create all tables on startup and apply light column migrations if needed."""
    from . import models  # noqa: F401
    Base.metadata.create_all(bind=engine)

    # Self-healing migration for SQLite columns
    from sqlalchemy import text
    try:
        with engine.connect() as conn:
            # Check jobs table columns
            res = conn.execute(text("PRAGMA table_info(jobs)"))
            columns = [row[1] for row in res.fetchall()]
            job_cols = {
                "screening_questions": "TEXT",
                "role_id": "VARCHAR",
                "priority": "VARCHAR",
                "salary_range": "VARCHAR",
                "location": "VARCHAR",
                "work_mode": "VARCHAR",
                "experience_level": "VARCHAR",
                "is_published": "BOOLEAN"
            }
            altered_jobs = False
            for col_name, col_type in job_cols.items():
                if col_name not in columns:
                    conn.execute(text(f"ALTER TABLE jobs ADD COLUMN {col_name} {col_type}"))
                    altered_jobs = True
            if altered_jobs:
                conn.commit()

            # Check candidates table columns
            res = conn.execute(text("PRAGMA table_info(candidates)"))
            columns = [row[1] for row in res.fetchall()]
            
            # Add missing assessment columns to candidates
            candidate_cols = {
                "assessment_token": "VARCHAR",
                "assessment_score": "FLOAT",
                "assessment_status": "VARCHAR",
                "assessment_responses": "TEXT",
                "assessment_violations": "INTEGER",
                "github_url": "VARCHAR",
                "github_analysis": "TEXT",
                "assessment_questions": "TEXT",
                "linkedin_url": "VARCHAR",
                "linkedin_analysis": "TEXT",
                "tech_fit": "VARCHAR",
                "client_readiness": "VARCHAR",
                "red_flags": "TEXT",
                "delivery_verdict": "VARCHAR",
                "client_feedback": "VARCHAR",
                "tech_rubric": "TEXT",
                "offer_date": "DATETIME",
                "joining_date": "DATETIME"
            }
            altered = False
            for col_name, col_type in candidate_cols.items():
                if col_name not in columns:
                    conn.execute(text(f"ALTER TABLE candidates ADD COLUMN {col_name} {col_type}"))
                    altered = True
            if altered:
                conn.commit()

            # Check interviews table columns
            res = conn.execute(text("PRAGMA table_info(interviews)"))
            columns = [row[1] for row in res.fetchall()]
            interview_cols = {
                "panel_type": "VARCHAR",
                "brief_shared": "VARCHAR",
                "verdict": "VARCHAR",
                "verdict_notes": "TEXT",
                "google_event_id": "VARCHAR",
                "google_meet_link": "VARCHAR",
                "gcal_link": "VARCHAR"
            }
            altered_interviews = False
            for col_name, col_type in interview_cols.items():
                if col_name not in columns:
                    conn.execute(text(f"ALTER TABLE interviews ADD COLUMN {col_name} {col_type}"))
                    altered_interviews = True
            if altered_interviews:
                conn.commit()

            # Check agent_runs table columns (added later — self-heal on start)
            res = conn.execute(text("PRAGMA table_info(agent_runs)"))
            columns = [row[1] for row in res.fetchall()]
            agent_run_cols = {
                "candidate_id": "INTEGER",
                "run_type": "VARCHAR",
            }
            altered_ar = False
            for col_name, col_type in agent_run_cols.items():
                if col_name not in columns:
                    conn.execute(text(f"ALTER TABLE agent_runs ADD COLUMN {col_name} {col_type}"))
                    altered_ar = True
            if altered_ar:
                # Back-fill run_type for any existing rows
                conn.execute(text("UPDATE agent_runs SET run_type = 'hiring' WHERE run_type IS NULL"))
                conn.commit()

            # Check screenings table columns
            res = conn.execute(text("PRAGMA table_info(screenings)"))
            columns = [row[1] for row in res.fetchall()]
            screening_cols = {
                "score_justification": "TEXT",
                "jd_vs_cv_score": "FLOAT",
                "jd_vs_linkedin_score": "FLOAT",
                "jd_vs_github_score": "FLOAT"
            }
            altered_screenings = False
            for col_name, col_type in screening_cols.items():
                if col_name not in columns:
                    conn.execute(text(f"ALTER TABLE screenings ADD COLUMN {col_name} {col_type}"))
                    altered_screenings = True
            if altered_screenings:
                conn.commit()
    except Exception as e:
        print(f"[DATABASE MIGRATION ERROR] Failed to apply column updates: {e}")

    # Seed initial data for dashboards (disabled)
    seed_dashboard_data()


def seed_dashboard_data():
    """Seed the database with presentation slide data if empty (Disabled)."""
    pass





from sqlalchemy import event
from .tenant import current_company_id

@event.listens_for(SessionLocal, "before_flush")
def receive_before_flush(session, flush_context, instances):
    company_id = current_company_id.get()
    if company_id is None:
        return
    for obj in session.new:
        if hasattr(obj, "company_id") and getattr(obj, "company_id") is None:
            obj.company_id = company_id

@event.listens_for(SessionLocal, "do_orm_execute")
def _add_tenant_filter(execute_state):
    company_id = current_company_id.get()
    if company_id is None:
        return
    
    if execute_state.is_select and not execute_state.is_column_load and not execute_state.is_relationship_load:
        for cd in execute_state.statement.column_descriptions:
            entity = cd.get("entity")
            if entity and hasattr(entity, "company_id"):
                execute_state.statement = execute_state.statement.filter(entity.company_id == company_id)
