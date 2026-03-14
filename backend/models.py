import os
import json
import logging
from typing import Optional

import ollama
from groq import Groq
from dotenv import load_dotenv

load_dotenv()
load_dotenv(dotenv_path=os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '.env'))
logger = logging.getLogger(__name__)


GENERATOR_SYSTEM_PROMPT = """
You are a Python code generator that produces high-quality, step-by-step solutions.

CRITICAL RULES:
1. Generate code incrementally - one logical step at a time
2. For EACH step, provide explicit reasoning explaining:
   - What requirement this step addresses
   - Why this approach was chosen
   - What assumptions are made (if any)
3. Output ONLY valid JSON in this exact format:
{
  "step_number": <integer>,
  "code": "<complete Python code for this step>",
  "reasoning": "<detailed explanation of this step>",
  "addresses_requirement": "<which part of the task this solves>",
  "assumptions": ["<list any assumptions made>"]
}

CONSTRAINTS:
- Maintain consistency with previous steps
- Do not introduce new libraries without explicit permission
- Preserve function signatures exactly as specified
- Handle edge cases mentioned in requirements

If this is the first step, initialize the solution structure.
If continuing from previous steps, build upon them WITHOUT contradicting earlier logic.
"""

CRITIC_SYSTEM_PROMPT = """
You are a rigorous code reviewer specializing in detecting logical drift and semantic inconsistencies.

YOUR ROLE:
Evaluate whether generated code maintains alignment with original requirements across multiple steps.

EVALUATION CRITERIA:
1. **Requirement Adherence**: Does this step address a stated requirement?
2. **Logical Consistency**: Does it contradict previous steps or make incompatible assumptions?
3. **Constraint Compliance**: Does it violate explicit constraints (e.g., banned libraries, complexity limits)?
4. **Semantic Correctness**: Does the logic make sense for the stated goal?

OUTPUT FORMAT (JSON only):
{
  "drift_detected": <boolean>,
  "drift_type": "<signature_drift|assumption_drift|logic_drift|constraint_violation|none>",
  "severity": <integer 1-10, where 10 is critical>,
  "explanation": "<detailed analysis of why drift occurred or confirmation of correctness>",
  "conflicting_step": <step_number if drift relates to earlier step, else null>,
  "suggestion": "<brief hint for correction if drift detected>"
}

BE STRICT: Even minor deviations from requirements should be flagged if they could lead to incorrect behavior.
"""



class CodeGenerator:
    """Wraps local Ollama llama3.2 for step-by-step code generation."""

    MODEL = "llama3.2"

    def __init__(self):
        self.total_tokens = 0
        try:
            ollama.list()
        except Exception as e:
            raise ValueError(
                f"Cannot connect to Ollama at localhost:11434 — is it running? ({e})"
            )

    def _chat(self, user_prompt: str) -> tuple[str, int]:
        """Call Ollama and return (text, tokens_used)."""
        response = ollama.chat(
            model=self.MODEL,
            messages=[
                {"role": "system", "content": GENERATOR_SYSTEM_PROMPT},
                {"role": "user",   "content": user_prompt},
            ],
            format="json",
            options={"temperature": 0.5, "num_predict": 4096},
        )
        text = response["message"]["content"]
        tokens = response.get("prompt_eval_count", 0) + response.get("eval_count", 0)
        return text, tokens

    def generate_step(self, task: str, constraints: list,
                      previous_steps: list, step_number: int) -> dict:
        """Generate the next code step."""
        prompt = f"""Task: {task}
Constraints: {json.dumps(constraints)}
Previous steps completed: {len(previous_steps)}

Generate step {step_number}. Context from previous steps:
{json.dumps(previous_steps, indent=2)}"""
        try:
            text, tokens = self._chat(prompt)
            self.total_tokens += tokens
            result = self._parse_response(text)
            result["step_number"] = step_number
            return result
        except Exception as e:
            logger.error(f"Ollama generation failed: {e}")
            raise

    def generate_correction(self, task: str, constraints: list,
                            previous_steps: list, step_number: int,
                            drift_info: dict) -> dict:
        """Regenerate a faulty step with corrective context."""
        prompt = f"""CORRECTION NEEDED:

Original Task: {task}

Your previous attempt for step {step_number} had this issue:
{drift_info.get('explanation', 'Validation failed')}

Previous valid steps (DO NOT MODIFY):
{json.dumps(previous_steps, indent=2)}

Task: Regenerate ONLY step {step_number} to fix:
{drift_info.get('suggestion', 'the identified issue')}

Ensure this step:
1. Addresses: {drift_info.get('addresses_requirement', 'the stated requirement')}
2. Does NOT contradict previous steps
3. Adheres to all constraints: {json.dumps(constraints)}"""
        try:
            text, tokens = self._chat(prompt)
            self.total_tokens += tokens
            result = self._parse_response(text)
            result["step_number"] = step_number
            return result
        except Exception as e:
            logger.error(f"Ollama correction failed: {e}")
            raise

    def generate_baseline(self, task: str, constraints: list) -> dict:
        """Generate code without self-correction (baseline evaluation)."""
        prompt = f"""Task: {task}
Constraints: {json.dumps(constraints)}

Generate a complete Python solution in a single step.
Provide the full implementation as step 1."""
        try:
            text, tokens = self._chat(prompt)
            self.total_tokens += tokens
            result = self._parse_response(text)
            result["step_number"] = 1
            return result
        except Exception as e:
            logger.error(f"Ollama baseline generation failed: {e}")
            raise

    @staticmethod
    def _parse_response(text: str) -> dict:
        """Parse JSON from Gemini response, handling markdown code fences and truncation."""
        text = text.strip()
        
        # Helper to try parsing a string
        def try_parse(s):
            s = s.strip()
            # Remove possible markdown code fences
            if s.startswith("```"):
                lines = s.splitlines()
                if len(lines) > 1:
                    if lines[0].strip().startswith("```"):
                        s = "\n".join(lines[1:])
                    if s.endswith("```"):
                        s = s[:-3]
            s = s.strip()
            if s.startswith("json"):
                s = s[4:].strip()
            try:
                return json.loads(s)
            except json.JSONDecodeError:
                # Catch partial JSON if possible (very basic)
                if s.startswith("{") and not s.endswith("}"):
                    try:
                        return json.loads(s + '"}')
                    except:
                        pass
                return None

        # 1. Try direct parse
        result = try_parse(text)
        if result: return result

        # 2. Try extracting JSON block
        if "{" in text and "}" in text:
            start = text.find("{")
            end = text.rfind("}")
            result = try_parse(text[start:end+1])
            if result: return result

        raise ValueError(f"Could not parse JSON from response. Length: {len(text)}. Snippet: {text[:100]}...")

    def get_total_tokens(self) -> int:
        """Return total tokens used across all calls."""
        return self.total_tokens

    def reset_token_count(self):
        """Reset the token counter."""
        self.total_tokens = 0



class CodeCritic:
    """Wraps Groq Llama 3.1 70B for drift detection and validation."""

    def __init__(self):
        api_key = os.getenv("GROQ_API_KEY")
        if not api_key:
            raise ValueError("GROQ_API_KEY environment variable not set")

        self.client = Groq(api_key=api_key)
        self.model_name = "llama-3.3-70b-versatile"
        self.total_tokens = 0

    def evaluate_step(self, original_task: str, constraints: list,
                      previous_steps: list, current_step: dict) -> dict:
        """Evaluate a code step for drift using the LLM critic."""
        critic_prompt = f"""
Original Task: {original_task}
Constraints: {json.dumps(constraints)}

Previous Steps:
{json.dumps(previous_steps, indent=2)}

Current Step to Evaluate:
Code: {current_step.get('code', '')}
Reasoning: {current_step.get('reasoning', '')}

Question: Does this step maintain logical consistency with the original requirements and previous steps?
"""
        try:
            response = self.client.chat.completions.create(
                model=self.model_name,
                messages=[
                    {"role": "system", "content": CRITIC_SYSTEM_PROMPT},
                    {"role": "user", "content": critic_prompt},
                ],
                temperature=0.2,
                max_tokens=1000,
                response_format={"type": "json_object"},
            )

            if response.usage:
                self.total_tokens += response.usage.total_tokens

            result = json.loads(response.choices[0].message.content)

            # Ensure expected fields exist
            result.setdefault("drift_detected", False)
            result.setdefault("drift_type", "none")
            result.setdefault("severity", 0)
            result.setdefault("explanation", "No issues found.")
            result.setdefault("conflicting_step", None)
            result.setdefault("suggestion", "")

            return result

        except json.JSONDecodeError:
            logger.error("Failed to parse Groq critic response as JSON")
            return {
                "drift_detected": False,
                "drift_type": "none",
                "severity": 0,
                "explanation": "Critic response was not valid JSON; treating as no drift.",
                "conflicting_step": None,
                "suggestion": "",
            }
        except Exception as e:
            logger.error(f"Groq critic evaluation failed: {e}")
            # On critic failure, don't block generation — treat as no drift
            return {
                "drift_detected": False,
                "drift_type": "none",
                "severity": 0,
                "explanation": f"Critic unavailable: {str(e)}",
                "conflicting_step": None,
                "suggestion": "",
            }

    def get_total_tokens(self) -> int:
        """Return total tokens used across all calls."""
        return self.total_tokens

    def reset_token_count(self):
        """Reset the token counter."""
        self.total_tokens = 0
