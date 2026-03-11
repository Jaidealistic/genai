"""
LangGraph Orchestrator for the Self-Correcting IDE Agent.
Defines the generate → validate → regenerate → finalize workflow.
"""

import json
import uuid
import logging
import time
from typing import TypedDict, List, Optional

from langgraph.graph import StateGraph, END

from models import CodeGenerator, CodeCritic
from validators import validate_ast, check_drift_rules
from database import StateDatabase

logger = logging.getLogger(__name__)

# ── State Definition ─────────────────────────────────────────────────────

class AgentState(TypedDict):
    task_id: str
    original_prompt: str
    constraints: List[str]
    current_step: int
    max_steps: int
    generated_steps: List[dict]
    drift_detected: bool
    correction_attempts: int
    final_code: Optional[str]
    session_id: int
    audit_trail: List[dict]
    error: Optional[str]


# ── Globals (initialized lazily) ─────────────────────────────────────────

_generator: Optional[CodeGenerator] = None
_critic: Optional[CodeCritic] = None
_db: Optional[StateDatabase] = None


def _get_generator() -> CodeGenerator:
    global _generator
    if _generator is None:
        _generator = CodeGenerator()
    return _generator


def _get_critic() -> CodeCritic:
    global _critic
    if _critic is None:
        _critic = CodeCritic()
    return _critic


def _get_db() -> StateDatabase:
    global _db
    if _db is None:
        _db = StateDatabase()
    return _db


def generate_task_id() -> str:
    """Generate a unique task ID."""
    return str(uuid.uuid4())[:8]


# ── Workflow Node Functions ──────────────────────────────────────────────

def generate_code_step(state: AgentState) -> AgentState:
    """Generate the next code step using Gemini."""
    generator = _get_generator()
    db = _get_db()
    step_num = state["current_step"]

    logger.info(f"Generating step {step_num}...")

    try:
        step_data = generator.generate_step(
            task=state["original_prompt"],
            constraints=state["constraints"],
            previous_steps=state["generated_steps"],
            step_number=step_num,
        )

        # Save step to database
        step_id = db.save_step(state["session_id"], step_data)
        step_data["step_id"] = step_id

        state["generated_steps"].append(step_data)
        state["drift_detected"] = False

        state["audit_trail"].append({
            "step": step_num,
            "action": "generated",
            "drift_detected": False,
            "explanation": f"Step {step_num} generated successfully.",
        })

    except Exception as e:
        logger.error(f"Generation failed at step {step_num}: {e}")
        state["error"] = str(e)
        state["audit_trail"].append({
            "step": step_num,
            "action": "generation_failed",
            "drift_detected": False,
            "explanation": f"Generation error: {str(e)}",
        })

    return state


def validate_step(state: AgentState) -> AgentState:
    """Validate the current step using AST + rule engine + LLM critic."""
    if state.get("error"):
        state["drift_detected"] = True
        return state

    db = _get_db()
    critic = _get_critic()
    current_step = state["generated_steps"][-1]
    step_id = current_step.get("step_id")
    code = current_step.get("code", "")

    logger.info(f"Validating step {state['current_step']}...")

    # 1. AST Syntax Check
    ast_result = validate_ast(code)
    if not ast_result["valid"]:
        state["drift_detected"] = True
        if step_id:
            db.log_validation(step_id, "ast", False, ast_result["message"])
            db.update_step_status(step_id, "drifted")

        state["generated_steps"][-1]["drift_info"] = {
            "drift_detected": True,
            "drift_type": "syntax_error",
            "severity": 10,
            "explanation": ast_result["message"],
            "suggestion": "Fix the syntax error in the generated code.",
        }

        state["audit_trail"].append({
            "step": state["current_step"],
            "action": "ast_validation_failed",
            "drift_detected": True,
            "explanation": ast_result["message"],
        })
        return state

    if step_id:
        db.log_validation(step_id, "ast", True, "Syntax valid")

    # 2. Rule-based drift checks
    rule_violation = check_drift_rules(
        code, state["constraints"], state["generated_steps"][:-1]
    )
    if rule_violation:
        state["drift_detected"] = True
        if step_id:
            db.log_validation(step_id, "rules", False, rule_violation)
            db.update_step_status(step_id, "drifted")

        state["generated_steps"][-1]["drift_info"] = {
            "drift_detected": True,
            "drift_type": "constraint_violation",
            "severity": 7,
            "explanation": rule_violation,
            "suggestion": "Fix the rule violation.",
        }

        state["audit_trail"].append({
            "step": state["current_step"],
            "action": "rule_validation_failed",
            "drift_detected": True,
            "explanation": rule_violation,
        })
        return state

    if step_id:
        db.log_validation(step_id, "rules", True, "No rule violations")

    # 3. LLM Critic evaluation
    try:
        critic_result = critic.evaluate_step(
            original_task=state["original_prompt"],
            constraints=state["constraints"],
            previous_steps=state["generated_steps"][:-1],
            current_step=current_step,
        )

        if step_id:
            db.log_validation(
                step_id, "llm_critic",
                not critic_result["drift_detected"],
                critic_result["explanation"],
                confidence_score=critic_result.get("severity", 0) / 10.0,
            )

        state["drift_detected"] = critic_result["drift_detected"]

        if critic_result["drift_detected"]:
            state["generated_steps"][-1]["drift_info"] = critic_result
            if step_id:
                db.update_step_status(step_id, "drifted")

            state["audit_trail"].append({
                "step": state["current_step"],
                "action": "llm_critic_drift_detected",
                "drift_detected": True,
                "explanation": critic_result["explanation"],
            })
        else:
            if step_id:
                db.update_step_status(step_id, "valid")

            state["audit_trail"].append({
                "step": state["current_step"],
                "action": "validated",
                "drift_detected": False,
                "explanation": critic_result["explanation"],
            })

    except Exception as e:
        logger.error(f"Critic evaluation failed: {e}")
        # On critic failure, treat step as valid (don't block generation)
        if step_id:
            db.log_validation(step_id, "llm_critic", True,
                              f"Critic unavailable: {str(e)}")
            db.update_step_status(step_id, "valid")
        state["drift_detected"] = False

    return state


def regenerate_step(state: AgentState) -> AgentState:
    """Regenerate a faulty step with corrective prompt."""
    generator = _get_generator()
    db = _get_db()
    faulty_step = state["generated_steps"][-1]
    drift_info = faulty_step.get("drift_info", {})
    step_num = state["current_step"]

    logger.info(
        f"Regenerating step {step_num} (attempt {state['correction_attempts'] + 1})..."
    )

    try:
        corrected_step = generator.generate_correction(
            task=state["original_prompt"],
            constraints=state["constraints"],
            previous_steps=state["generated_steps"][:-1],
            step_number=step_num,
            drift_info=drift_info,
        )

        # Log regeneration
        step_id = faulty_step.get("step_id")
        if step_id:
            db.log_regeneration(
                original_step_id=step_id,
                attempt_number=state["correction_attempts"] + 1,
                corrective_prompt=drift_info.get("explanation", ""),
                regenerated_code=corrected_step.get("code", ""),
            )

        # Replace faulty step
        corrected_step["step_id"] = step_id
        state["generated_steps"][-1] = corrected_step
        state["correction_attempts"] += 1
        state["drift_detected"] = False

        state["audit_trail"].append({
            "step": step_num,
            "action": "regenerated",
            "drift_detected": False,
            "explanation": f"Step regenerated (attempt {state['correction_attempts']}).",
        })

    except Exception as e:
        logger.error(f"Regeneration failed: {e}")
        state["correction_attempts"] += 1
        state["audit_trail"].append({
            "step": step_num,
            "action": "regeneration_failed",
            "drift_detected": True,
            "explanation": f"Regeneration error: {str(e)}",
        })

    return state


def should_regenerate(state: AgentState) -> str:
    """Decision function for conditional branching after validation."""
    if state.get("error"):
        return "finalize"

    if state["drift_detected"]:
        if state["correction_attempts"] < 3:
            return "regenerate"
        else:
            logger.warning("Max correction attempts reached. Finalizing with best effort.")
            return "finalize"

    # Check if we should generate more steps or finalize
    if state["current_step"] < state["max_steps"]:
        state["current_step"] += 1
        state["correction_attempts"] = 0  # Reset for next step
        return "continue"
    else:
        return "finalize"


def finalize_code(state: AgentState) -> AgentState:
    """Combine all valid steps into final code."""
    db = _get_db()

    # Combine code from all steps
    code_parts = []
    for step in state["generated_steps"]:
        code = step.get("code", "")
        if code:
            code_parts.append(code)

    final_code = "\n\n".join(code_parts)
    state["final_code"] = final_code

    # Mark session as completed
    status = "completed" if not state.get("error") else "failed"
    db.complete_session(state["session_id"], status)

    logger.info(f"Finalized code ({len(code_parts)} steps, {len(final_code)} chars)")

    return state


# ── Workflow Construction ────────────────────────────────────────────────

def build_workflow() -> StateGraph:
    """Build the LangGraph workflow."""
    workflow = StateGraph(AgentState)

    # Add nodes
    workflow.add_node("generate", generate_code_step)
    workflow.add_node("validate", validate_step)
    workflow.add_node("regenerate", regenerate_step)
    workflow.add_node("finalize", finalize_code)

    # Define edges
    workflow.set_entry_point("generate")
    workflow.add_edge("generate", "validate")

    # Conditional branching after validation
    workflow.add_conditional_edges(
        "validate",
        should_regenerate,
        {
            "regenerate": "regenerate",
            "continue": "generate",   # Next step
            "finalize": "finalize",
        },
    )

    # After regeneration, re-validate
    workflow.add_edge("regenerate", "validate")

    # Finalize leads to end
    workflow.add_edge("finalize", END)

    return workflow


# ── Main Entry Point ─────────────────────────────────────────────────────

async def run_generation_workflow(
    prompt: str,
    constraints: list[str] = None,
    max_steps: int = 3,
) -> dict:
    """Execute the complete generation workflow."""
    db = _get_db()
    generator = _get_generator()
    critic = _get_critic()

    # Reset token counters
    generator.reset_token_count()
    critic.reset_token_count()

    # Create task and session
    task_id = generate_task_id()
    db.create_task(task_id, prompt, constraints=constraints or [])
    session_id = db.create_session(task_id, "self_correcting")

    # Initialize state
    initial_state: AgentState = {
        "task_id": task_id,
        "original_prompt": prompt,
        "constraints": constraints or [],
        "current_step": 1,
        "max_steps": max_steps,
        "generated_steps": [],
        "drift_detected": False,
        "correction_attempts": 0,
        "final_code": None,
        "session_id": session_id,
        "audit_trail": [],
        "error": None,
    }

    # Build and compile workflow
    workflow = build_workflow()
    app = workflow.compile()

    start_time = time.time()

    # Run workflow
    final_state = await app.ainvoke(initial_state)

    execution_time = time.time() - start_time
    total_tokens = generator.get_total_tokens() + critic.get_total_tokens()

    # Save evaluation results
    db.save_evaluation_result(
        session_id=session_id,
        final_code=final_state.get("final_code", ""),
        tests_passed=0,
        tests_total=0,
        total_tokens=total_tokens,
        total_corrections=final_state.get("correction_attempts", 0),
        execution_time=execution_time,
    )

    return {
        "final_code": final_state.get("final_code", ""),
        "steps": final_state.get("generated_steps", []),
        "correction_attempts": final_state.get("correction_attempts", 0),
        "total_tokens": total_tokens,
        "audit_trail": final_state.get("audit_trail", []),
        "execution_time": execution_time,
        "task_id": task_id,
        "session_id": session_id,
    }


async def run_baseline_generation(prompt: str, constraints: list[str] = None) -> dict:
    """Run baseline generation (single shot, no self-correction)."""
    db = _get_db()
    generator = _get_generator()

    generator.reset_token_count()

    task_id = generate_task_id()
    db.create_task(task_id, prompt, constraints=constraints or [])
    session_id = db.create_session(task_id, "baseline")

    start_time = time.time()

    try:
        step_data = generator.generate_baseline(prompt, constraints or [])
        db.save_step(session_id, step_data)
        final_code = step_data.get("code", "")
    except Exception as e:
        logger.error(f"Baseline generation failed: {e}")
        final_code = ""
        step_data = {"code": "", "reasoning": f"Error: {str(e)}"}

    execution_time = time.time() - start_time
    total_tokens = generator.get_total_tokens()

    db.complete_session(session_id, "completed")
    db.save_evaluation_result(
        session_id=session_id,
        final_code=final_code,
        tests_passed=0,
        tests_total=0,
        total_tokens=total_tokens,
        total_corrections=0,
        execution_time=execution_time,
    )

    return {
        "final_code": final_code,
        "steps": [step_data],
        "correction_attempts": 0,
        "total_tokens": total_tokens,
        "audit_trail": [],
        "execution_time": execution_time,
        "task_id": task_id,
        "session_id": session_id,
    }
