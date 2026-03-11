"""
Metrics Calculation and Analysis for the Self-Correcting IDE Agent.
Includes comparative metrics, statistical significance testing, and drift pattern analysis.
"""

import logging
from typing import List

logger = logging.getLogger(__name__)


# ── Comparative Metrics ──────────────────────────────────────────────────

def calculate_metrics(baseline_results: list, system_results: list) -> dict:
    """Calculate comparative metrics between baseline and self-correcting system."""
    if not baseline_results or not system_results:
        return {"error": "Insufficient data for comparison"}

    # Pass@1 Rate
    baseline_pass1 = (
        sum(1 for r in baseline_results if r["passed"]) / len(baseline_results)
    )
    system_pass1 = (
        sum(1 for r in system_results if r["passed"]) / len(system_results)
    )

    # Token Efficiency
    baseline_avg_tokens = (
        sum(r["tokens"] for r in baseline_results) / len(baseline_results)
    )
    system_avg_tokens = (
        sum(r["tokens"] for r in system_results) / len(system_results)
    )
    token_savings = (
        ((baseline_avg_tokens - system_avg_tokens) / baseline_avg_tokens) * 100
        if baseline_avg_tokens > 0 else 0
    )

    # Inference Latency
    baseline_avg_time = (
        sum(r["time"] for r in baseline_results) / len(baseline_results)
    )
    system_avg_time = (
        sum(r["time"] for r in system_results) / len(system_results)
    )
    latency_overhead = (
        ((system_avg_time - baseline_avg_time) / baseline_avg_time) * 100
        if baseline_avg_time > 0 else 0
    )

    # Correction Statistics
    problems_with_corrections = [
        r for r in system_results if r.get("correction_count", 0) > 0
    ]
    avg_corrections = (
        sum(r["correction_count"] for r in system_results) / len(system_results)
    )
    correction_success_rate = (
        sum(1 for r in problems_with_corrections if r["passed"])
        / len(problems_with_corrections)
        if problems_with_corrections else 0
    )

    return {
        "baseline_pass1": round(baseline_pass1, 4),
        "system_pass1": round(system_pass1, 4),
        "improvement": round(system_pass1 - baseline_pass1, 4),
        "improvement_pct_points": round((system_pass1 - baseline_pass1) * 100, 1),
        "baseline_tokens": round(baseline_avg_tokens, 1),
        "system_tokens": round(system_avg_tokens, 1),
        "token_savings_pct": round(token_savings, 1),
        "baseline_time_sec": round(baseline_avg_time, 2),
        "system_time_sec": round(system_avg_time, 2),
        "latency_overhead_pct": round(latency_overhead, 1),
        "avg_corrections": round(avg_corrections, 2),
        "correction_success_rate": round(correction_success_rate, 4),
        "total_problems": len(system_results),
        "problems_with_drift": len(problems_with_corrections),
    }


# ── Statistical Significance ────────────────────────────────────────────

def test_significance(baseline_results: list, system_results: list) -> dict:
    """Paired t-test for statistical significance of pass@1 improvement."""
    try:
        from scipy.stats import ttest_rel

        baseline_scores = [1 if r["passed"] else 0 for r in baseline_results]
        system_scores = [1 if r["passed"] else 0 for r in system_results]

        if len(baseline_scores) != len(system_scores):
            return {"error": "Unequal sample sizes"}

        if len(set(baseline_scores)) == 1 and len(set(system_scores)) == 1:
            return {
                "t_statistic": 0,
                "p_value": 1.0,
                "significant": False,
                "note": "No variance in scores",
            }

        t_stat, p_value = ttest_rel(baseline_scores, system_scores)

        return {
            "t_statistic": round(t_stat, 4),
            "p_value": round(p_value, 6),
            "significant": p_value < 0.05,
            "significance_level": (
                "p < 0.01" if p_value < 0.01
                else "p < 0.05" if p_value < 0.05
                else f"p = {round(p_value, 4)}"
            ),
        }

    except ImportError:
        logger.warning("scipy not installed -- skipping significance test")
        return {"error": "scipy not installed", "significant": None}
    except Exception as e:
        logger.error(f"Significance test failed: {e}")
        return {"error": str(e), "significant": None}


# ── Drift Pattern Analysis ──────────────────────────────────────────────

def categorize_drift_patterns(system_results: list) -> dict:
    """Analyze where and why drift occurs across all problems."""
    drift_patterns = {
        "signature_drift": 0,
        "assumption_drift": 0,
        "logic_drift": 0,
        "constraint_violation": 0,
        "syntax_error": 0,
        "no_drift_but_failed": 0,
    }

    drift_step_distribution = []

    for result in system_results:
        if not result["passed"]:
            correction_count = result.get("correction_count", 0)
            if correction_count > 0:
                drift_info = result.get("drift_info", {})
                drift_type = drift_info.get("drift_type", "unknown")

                # Map to known categories
                if "signature" in drift_type.lower():
                    drift_patterns["signature_drift"] += 1
                elif "assumption" in drift_type.lower():
                    drift_patterns["assumption_drift"] += 1
                elif "logic" in drift_type.lower():
                    drift_patterns["logic_drift"] += 1
                elif "constraint" in drift_type.lower() or "rule" in drift_type.lower():
                    drift_patterns["constraint_violation"] += 1
                elif "syntax" in drift_type.lower() or "ast" in drift_type.lower():
                    drift_patterns["syntax_error"] += 1
                else:
                    drift_patterns["assumption_drift"] += 1  # Default bucket

                # Track at which step drift was detected
                drift_step = result.get("drift_detected_at_step")
                if drift_step is not None:
                    drift_step_distribution.append(drift_step)
            else:
                drift_patterns["no_drift_but_failed"] += 1

    avg_drift_step = (
        sum(drift_step_distribution) / len(drift_step_distribution)
        if drift_step_distribution else 0
    )

    return {
        "pattern_counts": drift_patterns,
        "avg_drift_step": round(avg_drift_step, 1),
        "drift_step_distribution": drift_step_distribution,
        "total_drifts_detected": sum(
            v for k, v in drift_patterns.items() if k != "no_drift_but_failed"
        ),
    }


# ── Report Generation ───────────────────────────────────────────────────

def generate_report(metrics: dict, significance: dict,
                    drift_analysis: dict) -> str:
    """Generate a human-readable evaluation report."""
    lines = [
        "",
        "=" * 60,
        "  EXPERIMENTAL RESULTS",
        "=" * 60,
        "",
        f"  Problems Evaluated: {metrics.get('total_problems', 'N/A')}",
        "",
        "  Pass@1 Accuracy:",
        f"    Baseline (Vanilla Gemini):      {metrics.get('baseline_pass1', 0):.1%}",
        f"    Self-Correcting System:         {metrics.get('system_pass1', 0):.1%}",
        f"    → Improvement: {metrics.get('improvement_pct_points', 0):+.1f} percentage points",
    ]

    if significance.get("significant") is not None:
        sig_str = significance.get("significance_level", "N/A")
        lines.append(f"    → Statistical Significance: {sig_str}")

    lines.extend([
        "",
        "  Token Efficiency:",
        f"    Baseline avg tokens/problem:   {metrics.get('baseline_tokens', 0):,.0f}",
        f"    System avg tokens/problem:     {metrics.get('system_tokens', 0):,.0f}",
        f"    → Savings: {metrics.get('token_savings_pct', 0):.1f}%",
        "",
        "  Inference Latency:",
        f"    Baseline avg time:             {metrics.get('baseline_time_sec', 0):.1f}s",
        f"    System avg time:               {metrics.get('system_time_sec', 0):.1f}s",
        f"    → Overhead: {metrics.get('latency_overhead_pct', 0):+.1f}%",
        "",
        "  Correction Statistics:",
        f"    Avg corrections per problem:   {metrics.get('avg_corrections', 0):.1f}",
        f"    Correction success rate:       {metrics.get('correction_success_rate', 0):.1%}",
        f"    Problems with detected drift:  {metrics.get('problems_with_drift', 0)}",
    ])

    if drift_analysis.get("total_drifts_detected", 0) > 0:
        patterns = drift_analysis["pattern_counts"]
        total_drifts = drift_analysis["total_drifts_detected"]
        lines.extend([
            "",
            f"  Drift Patterns ({total_drifts} problems with detected drift):",
        ])
        for pattern, count in patterns.items():
            if count > 0 and pattern != "no_drift_but_failed":
                pct = (count / total_drifts) * 100 if total_drifts > 0 else 0
                lines.append(f"    - {pattern}: {count} ({pct:.0f}%)")

        if drift_analysis["avg_drift_step"] > 0:
            lines.append(
                f"\n  Drift typically occurs at step {drift_analysis['avg_drift_step']:.1f} on average"
            )

    lines.extend(["", "=" * 60, ""])

    return "\n".join(lines)
