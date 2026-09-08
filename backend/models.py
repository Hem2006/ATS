"""
Stitch ATS — SQLAlchemy Models
All database tables for the ATS system.
"""

from datetime import datetime, timezone
from sqlalchemy import Column, UniqueConstraint, Integer, String, Float, Text, DateTime, ForeignKey, TypeDecorator

class UTCDateTime(TypeDecorator):
    impl = DateTime
    cache_ok = True

    def process_result_value(self, value, dialect):
        if value is not None and value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value
from sqlalchemy import Boolean
from sqlalchemy.orm import relationship
from .database import Base


class Company(Base):
    __tablename__ = "companies"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    name = Column(String, nullable=False)
    created_at = Column(UTCDateTime, default=lambda: datetime.now(timezone.utc))

    users = relationship("User", back_populates="company", cascade="all, delete-orphan")


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    email = Column(String, unique=True, index=True, nullable=False)
    password_hash = Column(String, nullable=False)
    role = Column(String, nullable=False)  # recruiter, tech_panel, delivery_head
    company_id = Column(Integer, ForeignKey("companies.id"))
    is_temporary_password = Column(Boolean, default=True)
    created_at = Column(UTCDateTime, default=lambda: datetime.now(timezone.utc))

    company = relationship("Company", back_populates="users")


class Job(Base):
    __tablename__ = "jobs"

    company_id = Column(Integer, ForeignKey("companies.id"), nullable=True)
    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    title = Column(String, nullable=False)
    description = Column(Text, nullable=False)
    jd_filename = Column(String, nullable=True)
    screening_questions = Column(Text, nullable=True)  # JSON list of questions
    role_id = Column(String, nullable=True)
    priority = Column(String, default="NORMAL", nullable=True)
    
    # New public job board fields
    salary_range = Column(String, nullable=True)
    location = Column(String, nullable=True)
    work_mode = Column(String, nullable=True)  # Remote, On-site, Hybrid
    experience_level = Column(String, nullable=True)
    is_published = Column(Boolean, default=False)
    
    created_at = Column(UTCDateTime, default=lambda: datetime.now(timezone.utc))

    screenings = relationship("Screening", back_populates="job", cascade="all, delete-orphan")


class Candidate(Base):
    __tablename__ = "candidates"

    company_id = Column(Integer, ForeignKey("companies.id"), nullable=True)
    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    name = Column(String, nullable=False)
    email = Column(String, nullable=True)
    phone = Column(String, nullable=True)
    role = Column(String, nullable=True)
    status = Column(String, default="uploaded")  # uploaded, screened, shortlisted, interviewed, offered, onboarded, rejected
    match_score = Column(Float, nullable=True)
    rejection_reason = Column(Text, nullable=True)
    resume_text = Column(Text, nullable=True)
    resume_filename = Column(String, nullable=True)
    assessment_token = Column(String, index=True, nullable=True)
    assessment_score = Column(Float, nullable=True)
    assessment_status = Column(String, nullable=True)  # pending, passed, failed
    assessment_responses = Column(Text, nullable=True)  # JSON representation of answers & AI feedback
    assessment_violations = Column(Integer, default=0, nullable=True)
    github_url = Column(String, nullable=True)
    github_analysis = Column(Text, nullable=True)
    linkedin_url = Column(String, nullable=True)
    linkedin_analysis = Column(Text, nullable=True)
    assessment_questions = Column(Text, nullable=True)
    
    # New Quality Gate fields
    tech_fit = Column(String, nullable=True)
    client_readiness = Column(String, nullable=True)
    red_flags = Column(Text, nullable=True)
    delivery_verdict = Column(String, default="NOT STARTED", nullable=True)
    client_feedback = Column(String, nullable=True)
    tech_rubric = Column(Text, nullable=True)
    offer_date = Column(UTCDateTime, nullable=True)
    joining_date = Column(UTCDateTime, nullable=True)
    
    created_at = Column(UTCDateTime, default=lambda: datetime.now(timezone.utc))

    screenings = relationship("Screening", back_populates="candidate", cascade="all, delete-orphan")
    interviews = relationship("Interview", back_populates="candidate", cascade="all, delete-orphan")
    onboarding_tasks = relationship("OnboardingTask", back_populates="candidate", cascade="all, delete-orphan")
    notes = relationship("CandidateNote", back_populates="candidate", cascade="all, delete-orphan")
    communications = relationship("CommunicationLog", back_populates="candidate", cascade="all, delete-orphan")


class Screening(Base):
    __tablename__ = "screenings"

    company_id = Column(Integer, ForeignKey("companies.id"), nullable=True)
    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    job_id = Column(Integer, ForeignKey("jobs.id"), nullable=False)
    candidate_id = Column(Integer, ForeignKey("candidates.id"), nullable=False)
    match_score = Column(Float, nullable=False)
    strengths = Column(Text, nullable=True)  # JSON string
    gaps = Column(Text, nullable=True)  # JSON string
    overall_summary = Column(Text, nullable=True)
    seniority_fit = Column(String, nullable=True)
    rejection_reason = Column(Text, nullable=True)
    score_justification = Column(Text, nullable=True)
    jd_vs_cv_score = Column(Float, nullable=True)
    jd_vs_linkedin_score = Column(Float, nullable=True)
    jd_vs_github_score = Column(Float, nullable=True)
    created_at = Column(UTCDateTime, default=lambda: datetime.now(timezone.utc))

    job = relationship("Job", back_populates="screenings")
    candidate = relationship("Candidate", back_populates="screenings")


class CandidateNote(Base):
    __tablename__ = "candidate_notes"

    company_id = Column(Integer, ForeignKey("companies.id"), nullable=True)
    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    candidate_id = Column(Integer, ForeignKey("candidates.id"), nullable=False)
    author = Column(String, nullable=False, default="Recruiter")
    content = Column(Text, nullable=False)
    created_at = Column(UTCDateTime, default=lambda: datetime.now(timezone.utc))

    candidate = relationship("Candidate", back_populates="notes")


class Interview(Base):
    __tablename__ = "interviews"

    company_id = Column(Integer, ForeignKey("companies.id"), nullable=True)
    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    candidate_id = Column(Integer, ForeignKey("candidates.id"), nullable=False)
    interviewer_name = Column(String, nullable=False)
    scheduled_at = Column(UTCDateTime, nullable=False)
    duration_mins = Column(Integer, default=45)
    status = Column(String, default="pending")  # pending, confirmed, completed, cancelled
    notes = Column(Text, nullable=True)
    
    # New technical panel fields
    panel_type = Column(String, nullable=True)
    brief_shared = Column(String, default="No", nullable=True)
    verdict = Column(String, default="PENDING", nullable=True)
    verdict_notes = Column(Text, nullable=True)
    
    # Google Calendar integration fields
    google_event_id = Column(String, nullable=True)
    google_meet_link = Column(String, nullable=True)
    gcal_link = Column(String, nullable=True)
    
    created_at = Column(UTCDateTime, default=lambda: datetime.now(timezone.utc))

    candidate = relationship("Candidate", back_populates="interviews")


class OnboardingTask(Base):
    __tablename__ = "onboarding_tasks"

    company_id = Column(Integer, ForeignKey("companies.id"), nullable=True)
    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    candidate_id = Column(Integer, ForeignKey("candidates.id"), nullable=False)
    category = Column(String, nullable=False)  # equipment, access, documentation
    task_name = Column(String, nullable=False)
    status = Column(String, default="pending")  # pending, done
    created_at = Column(UTCDateTime, default=lambda: datetime.now(timezone.utc))

    candidate = relationship("Candidate", back_populates="onboarding_tasks")


class Activity(Base):
    __tablename__ = "activities"

    company_id = Column(Integer, ForeignKey("companies.id"), nullable=True)
    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    action = Column(String, nullable=False)  # e.g. "New applicant", "Interview scheduled"
    description = Column(Text, nullable=False)
    icon = Column(String, default="📋")
    color = Column(String, default="#6366f1")
    created_at = Column(UTCDateTime, default=lambda: datetime.now(timezone.utc))


class SystemSetting(Base):
    __tablename__ = "system_settings"
    __table_args__ = (UniqueConstraint('company_id', 'key', name='_company_key_uc'),)

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=True)
    key = Column(String, index=True)
    value = Column(String, nullable=True)


class SpendLog(Base):
    __tablename__ = "spend_logs"

    company_id = Column(Integer, ForeignKey("companies.id"), nullable=True)
    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    role_id = Column(String, nullable=False)
    role = Column(String, nullable=False)
    amount = Column(Float, nullable=False)
    approval_level = Column(String, nullable=False)  # Standard, Elevated, Significant
    approver = Column(String, nullable=False)
    status = Column(String, default="PENDING")  # APPROVED, SELF-APPROVED, PENDING
    created_at = Column(UTCDateTime, default=lambda: datetime.now(timezone.utc))


class TAActivityLog(Base):
    __tablename__ = "ta_activity_logs"

    company_id = Column(Integer, ForeignKey("companies.id"), nullable=True)
    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    date = Column(String, nullable=False)  # e.g. "Mon 2 Jun"
    activity = Column(String, nullable=False)  # e.g. "New candidates sourced"
    role_ids = Column(String, nullable=True)  # e.g. "DR-042, DR-043"
    detail = Column(Text, nullable=False)
    outcome = Column(String, nullable=True)
    created_at = Column(UTCDateTime, default=lambda: datetime.now(timezone.utc))


class AgentRun(Base):
    """
    One autonomous run of the Hiring Agent.

    An AgentRun owns a goal, a target job, a status (running / completed / failed / verified),
    a final outcome summary, and an ordered list of AgentStep rows that record every
    thought, tool call, observation, and adaptation the agent produced.
    """
    __tablename__ = "agent_runs"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=True)
    job_id = Column(Integer, ForeignKey("jobs.id"), nullable=True)
    candidate_id = Column(Integer, ForeignKey("candidates.id"), nullable=True)
    run_type = Column(String, default="hiring", nullable=False)  # hiring | investigation
    goal = Column(Text, nullable=False)
    status = Column(String, default="running", nullable=False)  # running|completed|failed|verified
    outcome_summary = Column(Text, nullable=True)
    verification_result = Column(Text, nullable=True)  # JSON string from self-verifier OR investigation trust report
    adaptations_count = Column(Integer, default=0, nullable=False)
    tools_called = Column(Integer, default=0, nullable=False)
    started_at = Column(UTCDateTime, default=lambda: datetime.now(timezone.utc))
    finished_at = Column(UTCDateTime, nullable=True)

    steps = relationship("AgentStep", back_populates="run", cascade="all, delete-orphan", order_by="AgentStep.step_index")


class AgentStep(Base):
    """
    A single step in an AgentRun.

    kind is one of:
      - thought       : model's chain-of-thought / plan for the next move
      - tool_call     : the agent invoked a tool
      - observation   : tool result returned to the agent
      - adaptation    : agent changed strategy in response to a bad observation
      - verification  : self-verifier judge output
      - final         : final outcome
    """
    __tablename__ = "agent_steps"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    run_id = Column(Integer, ForeignKey("agent_runs.id"), nullable=False)
    step_index = Column(Integer, nullable=False)
    kind = Column(String, nullable=False)
    tool_name = Column(String, nullable=True)
    content = Column(Text, nullable=True)          # human-readable text
    payload = Column(Text, nullable=True)          # JSON of args or result
    created_at = Column(UTCDateTime, default=lambda: datetime.now(timezone.utc))

    run = relationship("AgentRun", back_populates="steps")


class CommunicationLog(Base):
    __tablename__ = "communication_logs"

    company_id = Column(Integer, ForeignKey("companies.id"), nullable=True)
    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    candidate_id = Column(Integer, ForeignKey("candidates.id"), nullable=False)
    type = Column(String, nullable=False)  # email | interview | system
    subject = Column(String, nullable=True)
    body = Column(Text, nullable=False)
    sender = Column(String, nullable=False, default="Recruiter")
    recipient = Column(String, nullable=False)
    created_at = Column(UTCDateTime, default=lambda: datetime.now(timezone.utc))

    candidate = relationship("Candidate", back_populates="communications")


