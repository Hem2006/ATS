"""
Seed two demo candidates for the Investigator demo:
  - Alex Chen — real, verifiable GitHub (@torvalds), moderate claims
  - Priya Sharma — extraordinary claims, fake GitHub username → should get shredded

Run:
    python -m backend.seed_investigator_demo
"""
from backend.database import SessionLocal, init_db
from backend.models import Company, Candidate


ALEX_RESUME = """Alex Chen
Senior Systems Engineer

Contact: alex.chen@example.com · github.com/torvalds

EXPERIENCE
Linux Foundation — 15+ years — Kernel maintainer and contributor.
Deep experience in the kernel tree, filesystems, and distributed VCS design.
Worked on Git and related tooling.

SKILLS
C at scale, systems programming, code review, distributed collaboration.
"""

PRIYA_RESUME = """Priya Sharma
Senior AI/ML Engineer

Contact: priya.sharma@example.com · github.com/nonexistent-user-98765-priya-xyz

EXPERIENCE
Google Brain — 10 years — Led all research on transformer scaling.
Published 40 papers at NeurIPS and ICML on foundation model architecture.
Deployed models serving 3 billion users daily.
Previously invented the attention mechanism (2015).

SKILLS
PyTorch, JAX, distributed training on 10,000+ GPUs, CUDA kernel optimization,
transformer scaling laws, mixture-of-experts, LLM alignment, RLHF.
"""


def main():
    init_db()
    db = SessionLocal()

    companies = db.query(Company).all()
    if not companies:
        print("No company in DB. Create one via signup first, then re-run.")
        return

    # Purge any earlier demo rows (across all tenants) so seeds are idempotent.
    db.query(Candidate).filter(Candidate.email.in_([
        "alex.chen@example.com", "priya.sharma@example.com",
    ])).delete()
    db.commit()

    # Seed one pair per company so whichever recruiter logs in can see them.
    for company in companies:
        alex = Candidate(
            company_id=company.id,
            name="Alex Chen (Demo)",
            email="alex.chen@example.com",
            role="Senior Systems Engineer",
            resume_text=ALEX_RESUME,
            github_url="https://github.com/torvalds",
            status="uploaded",
        )
        priya = Candidate(
            company_id=company.id,
            name="Priya Sharma (Demo)",
            email="priya.sharma@example.com",
            role="Senior AI/ML Engineer",
            resume_text=PRIYA_RESUME,
            github_url="https://github.com/nonexistent-user-98765-priya-xyz",
            status="uploaded",
        )
        db.add(alex); db.add(priya); db.commit()
        print(f"  Seeded into company #{company.id} '{company.name}':")
        print(f"    #{alex.id}  {alex.name}  (real GitHub — MODERATE/HIGH expected)")
        print(f"    #{priya.id} {priya.name}  (fake GitHub, wild claims — HIGH_RISK expected)")
    db.close()


if __name__ == "__main__":
    main()
