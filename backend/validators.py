"""
Validation Layer for the Self-Correcting IDE Agent.
Includes AST syntax validation, rule-based drift detection, and helper extractors.
"""

import ast
import builtins
from typing import List, Optional


# ── AST Syntax Validator ─────────────────────────────────────────────────

def validate_ast(code: str) -> dict:
    """Deterministic syntax validation using Python's ast module."""
    try:
        tree = ast.parse(code)
        return {
            "valid": True,
            "message": "Syntax valid",
            "ast_tree": tree,
        }
    except SyntaxError as e:
        return {
            "valid": False,
            "message": f"Syntax error at line {e.lineno}: {e.msg}",
            "error_type": "SyntaxError",
        }
    except Exception as e:
        return {
            "valid": False,
            "message": f"Unexpected error: {str(e)}",
            "error_type": type(e).__name__,
        }


# ── Helper Extractors ───────────────────────────────────────────────────

def extract_function_signature(code: str) -> Optional[str]:
    """Extract the first function definition signature from code."""
    try:
        tree = ast.parse(code)
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef):
                args = [arg.arg for arg in node.args.args]
                return f"{node.name}({', '.join(args)})"
    except Exception:
        pass
    return None


def extract_all_function_signatures(code: str) -> List[str]:
    """Extract all function definition signatures from code."""
    signatures = []
    try:
        tree = ast.parse(code)
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef):
                args = [arg.arg for arg in node.args.args]
                signatures.append(f"{node.name}({', '.join(args)})")
    except Exception:
        pass
    return signatures


def extract_imports(code: str) -> List[str]:
    """Extract all imported module names from code."""
    imports = []
    try:
        tree = ast.parse(code)
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imports.extend([alias.name for alias in node.names])
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    imports.append(node.module)
    except Exception:
        pass
    return imports


def extract_defined_variables(code: str) -> List[str]:
    """Extract all variable names defined (assigned to) in code."""
    defined = []
    try:
        tree = ast.parse(code)
        for node in ast.walk(tree):
            # Variable assignments
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name):
                        defined.append(target.id)
            # Augmented assignments (+=, etc.)
            elif isinstance(node, ast.AugAssign):
                if isinstance(node.target, ast.Name):
                    defined.append(node.target.id)
            # Function definitions
            elif isinstance(node, ast.FunctionDef):
                defined.append(node.name)
                # Function parameters
                for arg in node.args.args:
                    defined.append(arg.arg)
            # For loop variables
            elif isinstance(node, ast.For):
                if isinstance(node.target, ast.Name):
                    defined.append(node.target.id)
            # With statement variables
            elif isinstance(node, ast.With):
                for item in node.items:
                    if item.optional_vars and isinstance(item.optional_vars, ast.Name):
                        defined.append(item.optional_vars.id)
            # Class definitions
            elif isinstance(node, ast.ClassDef):
                defined.append(node.name)
            # List comprehension variables
            elif isinstance(node, ast.ListComp):
                for generator in node.generators:
                    if isinstance(generator.target, ast.Name):
                        defined.append(generator.target.id)
    except Exception:
        pass
    return list(set(defined))


def extract_used_variables(code: str) -> List[str]:
    """Extract all variable names used (loaded) in code."""
    used = []
    try:
        tree = ast.parse(code)
        for node in ast.walk(tree):
            if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load):
                used.append(node.id)
    except Exception:
        pass
    return list(set(used))


def get_builtins() -> List[str]:
    """Return list of Python builtin names."""
    return dir(builtins)


def extract_allowed_from_constraints(constraints: List[str]) -> List[str]:
    """
    Extract allowed import names from constraint strings.
    If no import constraints are specified, allow standard library modules.
    """
    allowed = []
    import_keywords = ["import", "library", "module", "use"]

    for constraint in constraints:
        lower = constraint.lower()
        # Check if constraint explicitly allows certain imports
        if any(kw in lower for kw in import_keywords):
            # Try to extract module names from the constraint
            words = constraint.split()
            for word in words:
                cleaned = word.strip(",.;:'\"()[]")
                if cleaned and not cleaned.lower() in import_keywords:
                    allowed.append(cleaned)

    # If no specific constraints on imports, allow common standard library
    if not allowed:
        allowed = [
            "math", "os", "sys", "re", "json", "collections", "itertools",
            "functools", "typing", "string", "random", "datetime", "copy",
            "heapq", "bisect", "operator", "decimal", "fractions",
            "statistics", "hashlib", "abc", "enum", "dataclasses",
        ]

    return allowed


# ── Drift Rule Engine ────────────────────────────────────────────────────

def check_drift_rules(current_code: str, constraints: List[str],
                      previous_steps: List[dict]) -> Optional[str]:
    """
    Apply hardcoded drift detection rules.
    Returns a string describing the violation, or None if no drift.
    """

    # Rule 1: Signature drift — check if function signatures changed
    if previous_steps:
        prev_code = previous_steps[0].get('code', '')
        prev_signature = extract_function_signature(prev_code)
        curr_signature = extract_function_signature(current_code)
        if prev_signature and curr_signature and prev_signature != curr_signature:
            return (
                f"Signature drift: Changed from '{prev_signature}' "
                f"to '{curr_signature}'"
            )

    # Rule 2: Unauthorized imports
    current_imports = extract_imports(current_code)
    allowed_imports = extract_allowed_from_constraints(constraints)
    unauthorized = set(current_imports) - set(allowed_imports)
    if unauthorized:
        return f"Unauthorized imports: {unauthorized}"

    # Rule 3: Undefined variable usage
    if previous_steps:
        # Collect all defined variables from previous steps
        all_prev_code = "\n".join([s.get('code', '') for s in previous_steps])
        defined_vars = extract_defined_variables(all_prev_code)

        # Add variables defined in current code
        curr_defined = extract_defined_variables(current_code)
        all_defined = set(defined_vars) | set(curr_defined)

        # Get used variables
        used_vars = extract_used_variables(current_code)

        # Subtract builtins and defined variables
        builtin_names = set(get_builtins())
        # Also allow common names
        common_names = {
            "print", "len", "range", "int", "str", "float", "list",
            "dict", "set", "tuple", "bool", "None", "True", "False",
            "type", "isinstance", "enumerate", "zip", "map", "filter",
            "sorted", "reversed", "sum", "min", "max", "abs", "any",
            "all", "input", "open", "super", "self", "cls",
        }

        undefined = set(used_vars) - all_defined - builtin_names - common_names

        # Also remove imported names
        imported_names = set(extract_imports(current_code))
        imported_names |= set(extract_imports(all_prev_code))
        undefined -= imported_names

        if undefined:
            return f"References undefined variables: {undefined}"

    return None  # No drift detected
