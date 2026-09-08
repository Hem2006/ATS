import os
import sys
from datetime import datetime, timezone
from passlib.context import CryptContext
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parent.parent))

from backend.database import SessionLocal, init_db
from backend.models import Company, User, Job, Candidate, Screening, Interview, SystemSetting

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

def main():
    db = SessionLocal()
    
    # Check if we already have it
    c = db.query(Company).filter(Company.name == "Acme Corp").first()
    if c:
        print("Acme Corp already exists!")
        return

    print("Creating Acme Corp...")
    c = Company(name="Acme Corp")
    db.add(c)
    db.commit()
    db.refresh(c)

    # 1. Create Recruiter
    hashed = pwd_context.hash("admin123")
    rec = User(
        email="hr@acme.com",
        password_hash=hashed,
        role="recruiter",
        company_id=c.id,
        is_temporary_password=False # Easy testing
    )
    db.add(rec)
    
    # 2. Create Tech Panel
    tech = User(
        email="tech@acme.com",
        password_hash=hashed,
        role="tech_panel",
        company_id=c.id,
        is_temporary_password=False
    )
    db.add(tech)
    
    # 3. Create Delivery Head
    delivery = User(
        email="delivery@acme.com",
        password_hash=hashed,
        role="delivery_head",
        company_id=c.id,
        is_temporary_password=False
    )
    db.add(delivery)
    
    db.commit()
    print("Created users: hr@acme.com, tech@acme.com, delivery@acme.com (password: admin123)")

if __name__ == "__main__":
    main()
