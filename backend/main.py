"""
FastAPI Backend for the Self-Correcting IDE Agent.
Provides REST API endpoints for code generation with drift detection.
"""

import logging
from typing import Optional
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from dotenv import load_dotenv

from orchestrator import run_generation_workflow, run_baseline_generation
from database import StateDatabase

# Load environment variables
load_dotenv()

# Logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


# ── Lifespan ─────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application startup and shutdown events."""
    logger.info("Self-Correcting IDE Agent backend starting...")
    # Initialize database on startup
    db = StateDatabase()
    logger.info("Database initialized.")
    yield
    db.close()
    logger.info("Backend shutdown.")


# ── FastAPI App ──────────────────────────────────────────────────────────

app = FastAPI(
    title="Self-Correcting IDE Agent",
    description="Code generation with drift detection and self-correction",
    version="1.0.0",
    lifespan=lifespan,
)

# CORS for VS Code extension
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Request / Response Models ────────────────────────────────────────────

class GenerateRequest(BaseModel):
    prompt: str = Field(..., description="Description of the code to generate")
    constraints: list[str] = Field(
        default=[], description="Constraints for code generation"
    )
    max_steps: int = Field(
        default=3, ge=1, le=10,
        description="Maximum number of generation steps"
    )


class AuditEntry(BaseModel):
    step: int
    action: str
    drift_detected: bool
    explanation: str


class GenerateResponse(BaseModel):
    final_code: str
    steps_count: int
    corrections: int
    tokens_used: int
    execution_time: float
    audit_trail: list[AuditEntry]
    task_id: Optional[str] = None


class BaselineRequest(BaseModel):
    prompt: str = Field(..., description="Description of the code to generate")
    constraints: list[str] = Field(
        default=[], description="Constraints for code generation"
    )


class BaselineResponse(BaseModel):
    final_code: str
    tokens_used: int
    execution_time: float
    task_id: Optional[str] = None


# ── Endpoints ────────────────────────────────────────────────────────────

@app.post("/generate", response_model=GenerateResponse)
async def generate_code(request: GenerateRequest):
    """Generate code with self-correcting drift detection."""
    try:
        logger.info(f"Received generation request: {request.prompt[:80]}...")

        result = await run_generation_workflow(
            prompt=request.prompt,
            constraints=request.constraints,
            max_steps=request.max_steps,
        )

        audit_trail = [
            AuditEntry(
                step=entry.get("step", 0),
                action=entry.get("action", "unknown"),
                drift_detected=entry.get("drift_detected", False),
                explanation=entry.get("explanation", ""),
            )
            for entry in result.get("audit_trail", [])
        ]

        return GenerateResponse(
            final_code=result.get("final_code", ""),
            steps_count=len(result.get("steps", [])),
            corrections=result.get("correction_attempts", 0),
            tokens_used=result.get("total_tokens", 0),
            execution_time=round(result.get("execution_time", 0), 2),
            audit_trail=audit_trail,
            task_id=result.get("task_id"),
        )

    except ValueError as e:
        # Missing API keys etc.
        logger.error(f"Configuration error: {e}")
        raise HTTPException(status_code=503, detail=str(e))
    except Exception as e:
        logger.error(f"Generation failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/generate/baseline", response_model=BaselineResponse)
async def generate_baseline(request: BaselineRequest):
    """Generate code without self-correction (baseline for comparison)."""
    try:
        logger.info(f"Received baseline request: {request.prompt[:80]}...")

        result = await run_baseline_generation(
            prompt=request.prompt,
            constraints=request.constraints,
        )

        return BaselineResponse(
            final_code=result.get("final_code", ""),
            tokens_used=result.get("total_tokens", 0),
            execution_time=round(result.get("execution_time", 0), 2),
            task_id=result.get("task_id"),
        )

    except ValueError as e:
        logger.error(f"Configuration error: {e}")
        raise HTTPException(status_code=503, detail=str(e))
    except Exception as e:
        logger.error(f"Baseline generation failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {"status": "healthy", "service": "self-correcting-ide-agent"}


@app.get("/")
async def root():
    """Root endpoint with API info."""
    return {
        "name": "Self-Correcting IDE Agent API",
        "version": "1.0.0",
        "endpoints": {
            "POST /generate": "Generate code with drift detection",
            "POST /generate/baseline": "Generate code without self-correction",
            "GET /health": "Health check",
        },
    }
