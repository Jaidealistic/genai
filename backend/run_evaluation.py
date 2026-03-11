"""
Run Evaluation Script for the Self-Correcting IDE Agent.
Evaluates both baseline and self-correcting systems on HumanEval problems
and logs results to Weights & Biases.

Usage:
    python run_evaluation.py [--num-problems 10] [--no-wandb]
"""

import asyncio
import argparse
import json
import logging
import os
import sys
from datetime import datetime

from dotenv import load_dotenv

# Add parent to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from evaluation import (
    load_humaneval_problems,
    evaluate_problem_baseline,
    evaluate_problem_self_correcting,
)
from metrics import (
    calculate_metrics,
    test_significance,
    categorize_drift_patterns,
    generate_report,
)
from models import CodeGenerator
from orchestrator import run_generation_workflow
from database import StateDatabase

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


# ── W&B Integration ──────────────────────────────────────────────────────

def init_wandb(num_problems: int):
    """Initialize Weights & Biases logging."""
    try:
        import wandb

        wandb.init(
            project="self-correcting-agent",
            config={
                "model_generator": "gemini-1.5-flash",
                "model_critic": "llama-3.1-70b-versatile",
                "dataset": f"humaneval-{num_problems}",
                "max_correction_attempts": 3,
                "max_steps": 3,
            },
            name=f"eval-{datetime.now().strftime('%Y%m%d-%H%M%S')}",
        )
        return wandb
    except ImportError:
        logger.warning("wandb not installed. Metrics will only be printed.")
        return None
    except Exception as e:
        logger.warning(f"wandb init failed: {e}. Continuing without logging.")
        return None


# ── Main Evaluation Loop ────────────────────────────────────────────────

async def run_full_evaluation(num_problems: int = 10, use_wandb: bool = True):
    """Run the complete evaluation pipeline."""

    print("\n" + "=" * 60)
    print("  SELF-CORRECTING IDE AGENT - EVALUATION")
    print("=" * 60)
    print(f"\n  Problems: {num_problems}")
    print(f"  Generator: Gemini 1.5 Flash")
    print(f"  Critic: Llama 3.1 70B (Groq)")
    print(f"  W&B Logging: {'Enabled' if use_wandb else 'Disabled'}")
    print()

    # Initialize
    wandb = init_wandb(num_problems) if use_wandb else None
    generator = CodeGenerator()

    # Load problems
    print("Loading HumanEval problems...")
    problems = load_humaneval_problems(num_problems)
    print(f"  Loaded {len(problems)} problems\n")

    # ── Baseline Evaluation ──────────────────────────────────────────
    print("─" * 40)
    print("  Phase 1: BASELINE EVALUATION")
    print("─" * 40)

    baseline_results = []
    for i, problem in enumerate(problems):
        print(f"  [{i+1}/{len(problems)}] {problem['task_id']}...", end=" ")
        generator.reset_token_count()

        result = await evaluate_problem_baseline(problem, generator)
        baseline_results.append(result)

        status = "✓ PASS" if result["passed"] else "✗ FAIL"
        print(f"{status} ({result['tokens']} tokens, {result['time']:.1f}s)")

        if wandb:
            wandb.log({
                "baseline_pass": 1 if result["passed"] else 0,
                "baseline_tokens": result["tokens"],
                "baseline_time": result["time"],
                "problem_index": i,
            })

    baseline_pass_count = sum(1 for r in baseline_results if r["passed"])
    print(f"\n  Baseline: {baseline_pass_count}/{len(problems)} passed "
          f"({baseline_pass_count/len(problems):.1%})\n")

    # ── Self-Correcting Evaluation ───────────────────────────────────
    print("─" * 40)
    print("  Phase 2: SELF-CORRECTING EVALUATION")
    print("─" * 40)

    system_results = []
    for i, problem in enumerate(problems):
        print(f"  [{i+1}/{len(problems)}] {problem['task_id']}...", end=" ")

        result = await evaluate_problem_self_correcting(
            problem, run_generation_workflow
        )
        system_results.append(result)

        status = "✓ PASS" if result["passed"] else "✗ FAIL"
        corrections = result.get("correction_count", 0)
        corr_str = f" ({corrections} corrections)" if corrections > 0 else ""
        print(f"{status}{corr_str} ({result['tokens']} tokens, {result['time']:.1f}s)")

        if wandb:
            wandb.log({
                "system_pass": 1 if result["passed"] else 0,
                "system_tokens": result["tokens"],
                "system_time": result["time"],
                "corrections": corrections,
                "problem_index": i,
            })

    system_pass_count = sum(1 for r in system_results if r["passed"])
    print(f"\n  System: {system_pass_count}/{len(problems)} passed "
          f"({system_pass_count/len(problems):.1%})\n")

    # ── Analysis ─────────────────────────────────────────────────────
    print("─" * 40)
    print("  Phase 3: ANALYSIS")
    print("─" * 40)

    metrics = calculate_metrics(baseline_results, system_results)
    significance = test_significance(baseline_results, system_results)
    drift_analysis = categorize_drift_patterns(system_results)

    # Generate and print report
    report = generate_report(metrics, significance, drift_analysis)
    print(report)

    # Log summary to W&B
    if wandb:
        wandb.log({
            "baseline_pass1": metrics.get("baseline_pass1", 0),
            "system_pass1": metrics.get("system_pass1", 0),
            "improvement_pct_points": metrics.get("improvement_pct_points", 0),
            "token_savings_pct": metrics.get("token_savings_pct", 0),
            "avg_corrections": metrics.get("avg_corrections", 0),
            "correction_success_rate": metrics.get("correction_success_rate", 0),
        })
        wandb.finish()

    # Save results to JSON
    output = {
        "timestamp": datetime.now().isoformat(),
        "num_problems": len(problems),
        "metrics": metrics,
        "significance": significance,
        "drift_analysis": {
            k: v for k, v in drift_analysis.items()
            if k != "drift_step_distribution"
        },
        "baseline_summary": {
            "passed": baseline_pass_count,
            "total": len(problems),
        },
        "system_summary": {
            "passed": system_pass_count,
            "total": len(problems),
        },
    }

    results_path = os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        "evaluation_results.json",
    )
    with open(results_path, "w") as f:
        json.dump(output, f, indent=2)
    print(f"  Results saved to: {results_path}\n")

    return output


# ── CLI ──────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Run Self-Correcting IDE Agent Evaluation"
    )
    parser.add_argument(
        "--num-problems", type=int, default=10,
        help="Number of HumanEval problems to evaluate (default: 10)",
    )
    parser.add_argument(
        "--no-wandb", action="store_true",
        help="Disable Weights & Biases logging",
    )
    args = parser.parse_args()

    asyncio.run(
        run_full_evaluation(
            num_problems=args.num_problems,
            use_wandb=not args.no_wandb,
        )
    )


if __name__ == "__main__":
    main()
