"""
Stitch ATS — FastAPI Application
Main entry point for the backend API server.
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .database import init_db
from .routers import screening, dashboard, interviews, onboarding, settings, assessment, auth, candidate_portal, agent, investigator
from .auth_middleware import TenantMiddleware

app = FastAPI(
    title="Stitch ATS API",
    description="Backend API for Stitch ATS Demo",
    version="1.0.0"
)

# Add Multi-Tenancy Middleware
app.add_middleware(TenantMiddleware)

import os

# CORS — allow React dev server and production URLs
allowed_origins = [
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    "http://localhost:3000"
]

prod_origin = os.getenv("FRONTEND_URL")
if prod_origin:
    allowed_origins.append(prod_origin)
else:
    allowed_origins.append("*")

# If wildcard is in allowed origins, allow_credentials must be False in FastAPI CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True if "*" not in allowed_origins else False,
    allow_methods=["*"],
    allow_headers=["*"],
)

from fastapi.staticfiles import StaticFiles

# Include routers
app.include_router(screening.router)
app.include_router(dashboard.router)
app.include_router(interviews.router)
app.include_router(onboarding.router)
app.include_router(settings.router)
app.include_router(assessment.router)
app.include_router(auth.router)
app.include_router(candidate_portal.router)
app.include_router(agent.router)
app.include_router(investigator.router)

# Mount static files for recordings/resumes
UPLOAD_DIR = os.path.join(os.path.dirname(__file__), "uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)
app.mount("/uploads", StaticFiles(directory=UPLOAD_DIR), name="uploads")


@app.on_event("startup")
def startup():
    """Initialize database tables on startup."""
    init_db()

    if os.getenv("SEED_DEMO_DATA") == "true":
        from .mock_tenant_setup import main as seed_demo_data
        seed_demo_data()


@app.get("/")
def root():
    return {"message": "Stitch ATS API is running", "version": "1.0.0"}


@app.get("/api/health")
def health():
    return {"status": "healthy"}
