"""
Evaluation Pipeline for the Self-Correcting IDE Agent.
Loads HumanEval problems and evaluates both baseline and self-correcting systems.
"""

import logging
import time
import traceback
from typing import Optional

logger = logging.getLogger(__name__)


# ── Test Execution ───────────────────────────────────────────────────────

def evaluate_functional_correctness(generated_code: str, test_suite: list) -> dict:
    """Execute test cases against generated code in an isolated namespace."""
    passed_tests = 0
    failed_tests = []

    for i, test_case in enumerate(test_suite):
        try:
            namespace = {}
            exec(generated_code, namespace)
            exec(test_case["test_code"], namespace)
            passed_tests += 1
        except AssertionError as e:
            failed_tests.append({
                "test_index": i,
                "test": test_case["test_code"],
                "error": str(e),
                "error_type": "AssertionError",
            })
        except Exception as e:
            failed_tests.append({
                "test_index": i,
                "test": test_case["test_code"],
                "error": f"Runtime error: {str(e)}",
                "error_type": type(e).__name__,
            })

    total = len(test_suite)
    if total == 0:
        return {
            "passed": 0,
            "total": 0,
            "pass_rate": 0,
            "failed_details": [{"test_index": 0, "test": "N/A", "error": "No test cases provided", "error_type": "MetadataError"}],
        }

    return {
        "passed": passed_tests,
        "total": total,
        "pass_rate": passed_tests / total,
        "failed_details": failed_tests,
    }


# ── HumanEval Dataset Helpers ────────────────────────────────────────────

def load_humaneval_problems(num_problems: int = 100) -> list:
    """
    Load HumanEval problems from the datasets library.
    Returns a list of problem dicts with prompt, test, entry_point, etc.
    """
    try:
        from datasets import load_dataset

        dataset = load_dataset("openai_humaneval", split="test")
        problems = []

        for i, problem in enumerate(dataset):
            if i >= num_problems:
                break

            # Parse test cases from the canonical_solution + test fields
            test_code = problem.get("test", "")
            entry_point = problem.get("entry_point", "")

            # Build test suite
            test_suite = []
            if test_code:
                test_suite.append({
                    "test_code": test_code,
                    "description": f"HumanEval test for {entry_point}",
                })

            problems.append({
                "task_id": problem.get("task_id", f"humaneval_{i}"),
                "prompt": problem.get("prompt", ""),
                "canonical_solution": problem.get("canonical_solution", ""),
                "test": test_code,
                "entry_point": entry_point,
                "test_suite": test_suite,
            })

        logger.info(f"Loaded {len(problems)} HumanEval problems")
        return problems

    except ImportError:
        logger.warning("datasets library not installed. Using sample problems.")
        return _get_sample_problems()
    except Exception as e:
        logger.error(f"Failed to load HumanEval: {e}")
        return _get_sample_problems()


def _get_sample_problems() -> list:
    """Fallback sample problems if HumanEval dataset is unavailable."""
    return [
        {
            "task_id": "sample_0",
            "prompt": "Write a function called 'add' that takes two integers and returns their sum.",
            "canonical_solution": "def add(a, b):\n    return a + b",
            "entry_point": "add",
            "test_suite": [
                {"test_code": "assert add(1, 2) == 3"},
                {"test_code": "assert add(-1, 1) == 0"},
                {"test_code": "assert add(0, 0) == 0"},
            ],
        },
        {
            "task_id": "sample_1",
            "prompt": "Write a function called 'factorial' that computes the factorial of a non-negative integer.",
            "canonical_solution": "def factorial(n):\n    if n <= 1:\n        return 1\n    return n * factorial(n - 1)",
            "entry_point": "factorial",
            "test_suite": [
                {"test_code": "assert factorial(0) == 1"},
                {"test_code": "assert factorial(1) == 1"},
                {"test_code": "assert factorial(5) == 120"},
                {"test_code": "assert factorial(10) == 3628800"},
            ],
        },
        {
            "task_id": "sample_2",
            "prompt": "Write a function called 'is_palindrome' that checks if a string is a palindrome.",
            "canonical_solution": "def is_palindrome(s):\n    return s == s[::-1]",
            "entry_point": "is_palindrome",
            "test_suite": [
                {"test_code": "assert is_palindrome('racecar') == True"},
                {"test_code": "assert is_palindrome('hello') == False"},
                {"test_code": "assert is_palindrome('') == True"},
                {"test_code": "assert is_palindrome('a') == True"},
            ],
        },
        {
            "task_id": "sample_3",
            "prompt": "Write a function called 'fibonacci' that returns the nth Fibonacci number (0-indexed).",
            "canonical_solution": "def fibonacci(n):\n    if n <= 0:\n        return 0\n    elif n == 1:\n        return 1\n    a, b = 0, 1\n    for _ in range(2, n + 1):\n        a, b = b, a + b\n    return b",
            "entry_point": "fibonacci",
            "test_suite": [
                {"test_code": "assert fibonacci(0) == 0"},
                {"test_code": "assert fibonacci(1) == 1"},
                {"test_code": "assert fibonacci(10) == 55"},
            ],
        },
        {
            "task_id": "sample_4",
            "prompt": "Write a function called 'max_subarray_sum' that finds the maximum sum of a contiguous subarray.",
            "canonical_solution": "def max_subarray_sum(nums):\n    if not nums:\n        return 0\n    max_sum = current = nums[0]\n    for num in nums[1:]:\n        current = max(num, current + num)\n        max_sum = max(max_sum, current)\n    return max_sum",
            "entry_point": "max_subarray_sum",
            "test_suite": [
                {"test_code": "assert max_subarray_sum([1, -2, 3, 4, -1]) == 7"},
                {"test_code": "assert max_subarray_sum([-1]) == -1"},
                {"test_code": "assert max_subarray_sum([1, 2, 3]) == 6"},
            ],
        },
    ]


# ── Evaluation Runners ───────────────────────────────────────────────────

async def evaluate_problem_baseline(problem: dict, generator) -> dict:
    """Evaluate a single problem using baseline (no self-correction)."""
    start_time = time.time()
    tokens_before = generator.get_total_tokens()

    try:
        step_data = generator.generate_baseline(
            task=problem["prompt"],
            constraints=[],
        )
        code = step_data.get("code", "")
    except Exception as e:
        logger.error(f"Baseline generation failed for {problem['task_id']}: {e}")
        code = ""

    elapsed = time.time() - start_time
    tokens_used = generator.get_total_tokens() - tokens_before

    # Evaluate correctness
    test_result = evaluate_functional_correctness(code, problem.get("test_suite", []))

    return {
        "task_id": problem["task_id"],
        "passed": test_result["pass_rate"] == 1.0,
        "pass_rate": test_result["pass_rate"],
        "tests_passed": test_result["passed"],
        "tests_total": test_result["total"],
        "tokens": tokens_used,
        "time": elapsed,
        "code": code,
        "correction_count": 0,
        "failed_details": test_result["failed_details"],
    }


async def evaluate_problem_self_correcting(problem: dict, run_workflow_fn) -> dict:
    """Evaluate a single problem using the self-correcting system."""
    start_time = time.time()

    try:
        result = await run_workflow_fn(
            prompt=problem["prompt"],
            constraints=[],
            max_steps=3,
        )
        code = result.get("final_code", "")
        tokens_used = result.get("total_tokens", 0)
        correction_count = result.get("correction_attempts", 0)
        audit_trail = result.get("audit_trail", [])
    except Exception as e:
        logger.error(f"Self-correcting generation failed for {problem['task_id']}: {e}")
        code = ""
        tokens_used = 0
        correction_count = 0
        audit_trail = []

    elapsed = time.time() - start_time

    # Evaluate correctness
    test_result = evaluate_functional_correctness(code, problem.get("test_suite", []))

    # Extract drift info if present
    drift_info = {}
    for entry in audit_trail:
        if entry.get("drift_detected"):
            drift_info = {
                "drift_type": entry.get("action", "unknown"),
                "explanation": entry.get("explanation", ""),
            }
            break

    return {
        "task_id": problem["task_id"],
        "passed": test_result["pass_rate"] == 1.0,
        "pass_rate": test_result["pass_rate"],
        "tests_passed": test_result["passed"],
        "tests_total": test_result["total"],
        "tokens": tokens_used,
        "time": elapsed,
        "code": code,
        "correction_count": correction_count,
        "drift_info": drift_info,
        "drift_detected_at_step": next(
            (e.get("step") for e in audit_trail if e.get("drift_detected")),
            None,
        ),
        "audit_trail": audit_trail,
        "failed_details": test_result["failed_details"],
    }
