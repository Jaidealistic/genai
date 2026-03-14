# Self-Correcting IDE Agent

## Overview

A research-oriented code generation system that detects and corrects "logical drift" — the
tendency of LLMs to gradually deviate from original requirements across multi-step generation.
The system acts as an IDE extension (VS Code) backed by a Python FastAPI server that orchestrates
a two-model pipeline: **Gemini 1.5 Flash** generates code incrementally while **Groq Llama 3.3 70B**
acts as a strict critic reviewing each step before it is accepted.

The project also includes a full evaluation pipeline against the OpenAI HumanEval benchmark and
optional experiment tracking via Weights and Biases.

---

## Tech Stack

| Layer | Technology |
|---|---|
| Backend API | Python 3.10+, FastAPI, Uvicorn |
| Agent Orchestration | LangGraph 0.2 (StateGraph) |
| Code Generator (Actor) | Google Gemini 1.5 Flash via `google-generativeai` |
| Drift Critic | Groq Llama 3.3 70B via `groq` SDK |
| Validation | Python `ast` module (static), rule engine (heuristic) |
| Persistence | SQLite via `sqlite3` (stdlib) |
| Evaluation | HumanEval dataset via `datasets`, `scipy` for statistics |
| Experiment Tracking | Weights and Biases (`wandb`), optional |
| VS Code Extension | TypeScript, VS Code API, Axios |
| Extension Build | `tsc` (TypeScript compiler) |

---

## Project Structure

```
self-correcting-agent/
├── backend/                     # Python FastAPI server + agent logic
│   ├── main.py                  # FastAPI app: endpoints, CORS, lifespan
│   ├── orchestrator.py          # LangGraph workflow: generate→validate→regenerate→finalize
│   ├── models.py                # LLM client wrappers: CodeGenerator (Gemini), CodeCritic (Groq)
│   ├── validators.py            # AST syntax checker + rule-based drift detector
│   ├── database.py              # SQLite state persistence layer
│   ├── evaluation.py            # HumanEval loader + test executor
│   ├── metrics.py               # Comparative metrics, significance testing, drift analysis
│   ├── run_evaluation.py        # CLI script to run full evaluation pipeline
│   ├── evaluation_results.json  # Output file written by run_evaluation.py
│   └── requirements.txt         # Python dependencies (pinned versions)
│
├── vscode-extension/            # TypeScript VS Code extension
│   ├── src/
│   │   ├── extension.ts         # Extension entry: registers command, sidebar, status bar
│   │   └── api.ts               # AgentApiClient class wrapping the FastAPI REST endpoints
│   ├── package.json             # Extension manifest: commands, views, keybindings, config
│   ├── tsconfig.json            # TypeScript compiler config (ES2020, CommonJS, strict)
│   └── package-lock.json        # Locked Node dependency tree
│
├── .vscode/
│   ├── launch.json              # F5 launch config for extension development host
│   └── tasks.json               # Default build task: runs `npm run compile` in vscode-extension/
│
├── .gitignore                   # Excludes .env, __pycache__, *.db, node_modules, out/, wandb/
├── README.md                    # Formal project report (executive summary, setup, evaluation)
└── instructions.txt             # Original project specification / assignment brief
```

---

## Key Files and Their Purposes

### `backend/main.py`
FastAPI application. Defines three endpoints:
- `POST /generate` — triggers the full self-correcting LangGraph workflow
- `POST /generate/baseline` — single-shot generation without self-correction (for A/B comparison)
- `GET /health` — liveness probe used by the VS Code extension before each request

CORS is set to `allow_origins=["*"]` to allow the extension to connect on any port.
The `lifespan` context manager initialises and tears down the `StateDatabase` connection.

### `backend/orchestrator.py`
The core agent logic. Defines the `AgentState` TypedDict and four LangGraph nodes:

| Node | Function |
|---|---|
| `generate` | Calls `CodeGenerator.generate_step()` to produce the next code chunk |
| `validate` | Runs AST check, rule engine, then LLM critic in sequence |
| `regenerate` | Calls `CodeGenerator.generate_correction()` with drift context injected into the prompt |
| `finalize` | Joins all step code blocks with `\n\n` and marks the session complete |

The conditional edge `should_regenerate` routes:
- `"regenerate"` if drift detected and `correction_attempts < 3`
- `"continue"` (loops back to `generate`) if no drift and more steps remain
- `"finalize"` if max steps reached, max corrections exhausted, or an error occurred

Generator and critic are lazily initialized as module-level globals (`_generator`, `_critic`, `_db`).
The workflow graph is rebuilt and recompiled on every call to `run_generation_workflow()`.

### `backend/models.py`
Two classes:

**`CodeGenerator`** (Gemini 1.5 Flash)
- Uses `response_mime_type: "application/json"` to encourage structured output
- Temperature: 0.5 for generation, same for corrections
- `_parse_response()` handles malformed JSON: strips markdown fences, attempts bracket
  repair on truncated responses, falls back gracefully with a descriptive error

**`CodeCritic`** (Groq Llama 3.3 70B)
- Uses `response_format: {"type": "json_object"}` for reliable JSON output
- Temperature: 0.2 (low variance for consistent judgment)
- On any failure (JSON parse error, API error) the critic returns `drift_detected: False`
  so a critic outage never blocks generation

Both classes track token usage with `total_tokens` and expose `get_total_tokens()` /
`reset_token_count()`.

### `backend/validators.py`
Two-tier static validation:

1. **`validate_ast(code)`** — wraps `ast.parse()`; catches `SyntaxError` and returns a
   structured dict with `valid: bool` and `message`

2. **`check_drift_rules(current_code, constraints, previous_steps)`** — three sequential rules:
   - **Rule 1** Signature drift: compares first function signature in step 0 vs current step
   - **Rule 2** Unauthorized imports: extracts imports, checks against allowed list derived
     from constraint strings or a default standard-library whitelist
   - **Rule 3** Undefined variables: collects defined names from all previous steps and flags
     names used in the current step that have no definition

Helper functions (`extract_function_signature`, `extract_imports`, `extract_defined_variables`,
`extract_used_variables`) all use `ast.walk()` for reliable parsing.

### `backend/database.py`
`StateDatabase` wraps a SQLite connection. Schema:

| Table | Purpose |
|---|---|
| `tasks` | One row per unique prompt/task_id |
| `generation_sessions` | One per `/generate` call; tracks model names, timing, status |
| `generation_steps` | Each LangGraph step with code, reasoning, validation_status |
| `validations` | One row per (step, validator_type) — ast, rules, llm_critic |
| `regenerations` | Log of each corrective re-generation attempt |
| `evaluation_results` | Final aggregate metrics per session |
| `user_feedback` | Schema exists but no write path currently exists in the codebase |

The database file defaults to `agent_state.db` in whatever directory the server is run from
(i.e., `backend/agent_state.db` if started from the `backend/` directory).

### `backend/evaluation.py`
- `evaluate_functional_correctness()` — executes test cases via `exec()` in an isolated
  namespace dict; no sandbox, no subprocess isolation
- `load_humaneval_problems()` — loads the `openai_humaneval` HumanEval split from Hugging Face;
  falls back to 5 hardcoded sample problems if the library is unavailable
- `evaluate_problem_baseline()` / `evaluate_problem_self_correcting()` — async wrappers
  that call the generator/workflow and run correctness evaluation

### `backend/metrics.py`
Pure calculation functions: pass@1 rates, token efficiency, latency overhead, correction
statistics, paired t-test via `scipy.stats.ttest_rel`, and drift pattern categorization.
`generate_report()` formats results as a human-readable plaintext report.

### `backend/run_evaluation.py`
CLI entry point. Orchestrates the three-phase evaluation:
1. Baseline evaluation (all problems)
2. Self-correcting evaluation (all problems)
3. Statistical analysis and report printing

Writes `evaluation_results.json`. Integrates with W&B if `--no-wandb` is not passed.
Both phases include a 2-second `asyncio.sleep()` between problems for Gemini free-tier rate limiting.

### `vscode-extension/src/extension.ts`
Extension entry point. On activation:
- Registers command `self-correcting-agent.generate` (Ctrl+Shift+G on Windows/Linux, Cmd+Shift+G on macOS)
- Creates an `OutputChannel` named "Self-Correcting Agent" for displaying audit trails
- Registers `AgentViewProvider` as a tree data provider for the sidebar panel
- Creates a status bar item showing "$(hubot) AI Agent" on the right side

The generate command flow:
1. Reads `selfCorrectingAgent.apiUrl` and `selfCorrectingAgent.maxSteps` from VS Code settings
2. Health checks the backend via `GET /health`
3. Shows two `showInputBox` dialogs: prompt, then optional comma-separated constraints
4. Wraps the API call in `vscode.window.withProgress` (notification-style spinner)
5. On success: inserts code at the current cursor position, shows an info notification,
   and calls `showAuditTrail()` to populate the Output channel

### `vscode-extension/src/api.ts`
`AgentApiClient` class with three methods:
- `generateWithCorrection(request)` — POST /generate
- `generateBaseline(prompt, constraints)` — POST /generate/baseline
- `healthCheck()` — GET /health, returns boolean

Axios is configured with a 120-second timeout. No retry logic is implemented.

---

## Development Commands

### Backend

```bash
# Install dependencies (run from backend/)
pip install -r requirements.txt

# Set up environment (create .env at project root or in backend/)
GEMINI_API_KEY=your_key_here
GROQ_API_KEY=your_key_here
WANDB_API_KEY=your_key_here   # optional

# Start the development server (run from backend/)
python -m uvicorn main:app --reload --port 8000

# Run the evaluation pipeline (from backend/)
python run_evaluation.py --num-problems 10 --no-wandb

# Run with W&B tracking (requires WANDB_API_KEY)
python run_evaluation.py --num-problems 50
```

### VS Code Extension

```bash
# Install Node dependencies (run from vscode-extension/)
npm install

# Compile TypeScript to JS (output goes to vscode-extension/out/)
npm run compile

# Watch mode (auto-recompiles on save)
npm run watch
```

To launch the extension development host: open the project root in VS Code and press **F5**.
This triggers the default build task (TypeScript compile) then opens a new VS Code window with
the extension loaded.

---

## Coding Conventions

### Python (backend)

- **Module docstrings**: Every file starts with a triple-quoted docstring describing the module's role.
- **Section comments**: Use `# ── Section Name ───...` horizontal rule style to separate logical
  sections within a file.
- **Logging**: `logging.getLogger(__name__)` in every module. No `print()` in backend modules
  (only in `run_evaluation.py` for human-readable CLI output).
- **Type hints**: Used consistently on function signatures (`-> dict`, `-> AgentState`, etc.).
  `TypedDict` for the LangGraph state.
- **Pydantic models**: Request/response validation is done via Pydantic `BaseModel` classes
  defined in `main.py` (not in a separate schemas file).
- **Error handling**: Catch specific exceptions before broad `Exception`. On LLM failures, fail
  open (return a safe default) rather than propagating errors to the caller.
- **No test files**: There are no pytest files in the repository. The evaluation pipeline
  in `run_evaluation.py` serves as an integration test but is not a unit test suite.

### TypeScript (extension)

- **Strict mode**: `"strict": true` in tsconfig. All types must be explicit.
- **Interface naming**: Prefix with nothing (no `I` prefix) — `AuditEntry`, `GenerationResult`.
- **Private members**: Use the `private` keyword on class fields (e.g., `private client: AxiosInstance`).
- **Error handling**: Errors caught in the generate command handler extract `error?.response?.data?.detail`
  first (FastAPI detail format), then fall back to `error?.message`.
- **No test files**: The extension has no tests.

---

## Architecture Patterns

### Actor-Critic Pattern
The system separates code generation (Gemini as "Actor") from code evaluation (Groq as "Critic").
This is a deliberate design choice: using two different models from two different providers ensures
the critic has genuinely independent judgment and is less susceptible to the same blind spots as
the generator.

### LangGraph StateGraph
The workflow is a directed graph with a feedback loop:

```
generate → validate → [should_regenerate] → regenerate → validate (loop)
                   ↓                     ↓
                continue               finalize
                   ↓
                generate (next step)
```

State is passed as a single `AgentState` dict mutated by each node. Nodes return the full state
dict (LangGraph convention). The workflow is rebuilt and compiled (`.compile()`) on each
`run_generation_workflow()` call — this is simple but adds minimal overhead per request.

### Three-Layer Validation
Each step is validated in increasing order of cost/complexity:
1. **AST** (deterministic, free, fast) — rejects syntax errors immediately
2. **Rule engine** (deterministic, heuristic, fast) — rejects structural drift
3. **LLM critic** (probabilistic, expensive, slow) — catches semantic/logical drift

If layer 1 or 2 detects drift, layer 3 is skipped (early exit).

### Lazy Global Singletons
`_generator`, `_critic`, and `_db` in `orchestrator.py` are module-level globals initialized
on first access. This avoids re-creating LLM client connections on every request while keeping
the initialization path testable.

### Fail-Open Critic
The critic is explicitly designed to fail open: any exception or JSON parse error causes
`drift_detected` to be set to `False`. This is correct for the actor/critic relationship
— a temporarily unavailable critic should not halt code generation.

---

## Testing Approach

There is no formal unit test suite. The project has two testing mechanisms:

1. **Integration evaluation**: `run_evaluation.py` runs the full pipeline against HumanEval
   problems. This is the primary way to verify correctness of the generation + validation flow.

2. **Functional correctness**: `evaluation.py`'s `evaluate_functional_correctness()` runs
   generated code via `exec()` against assertion-based test cases.

**Warning**: `exec()` is used with no sandbox or subprocess isolation. Generated code runs
directly in the evaluation process. This is acceptable for a research prototype but would
require sandboxing (e.g., Docker, `subprocess`, or `RestrictedPython`) in any production scenario.

To add unit tests, pytest is not yet in `requirements.txt` but would be the natural choice.
Key units to test: `validate_ast()`, `check_drift_rules()`, and `_parse_response()`.

---

## Important Notes and Known Issues

### 1. Workflow Rebuilt on Every Request
`build_workflow()` and `workflow.compile()` are called inside `run_generation_workflow()` on
every HTTP request. LangGraph compilation is fast, but caching the compiled workflow as a module
global would be a minor performance improvement.

### 2. Model Name Mismatch in Database
`database.py`'s `create_session()` defaults `model_critic` to `"llama-3.1-70b-versatile"` (old
name), but `models.py` uses `"llama-3.3-70b-versatile"` (current name). The database records
the wrong model version for the critic.

### 3. Rule 1 Only Compares Against Step 0
`check_drift_rules()` compares the current step's function signature against `previous_steps[0]`
only. If step 0 defines no function but step 2 does, the signature check is skipped. The
comparison should accumulate all signatures from all previous steps.

### 4. Import Whitelist Logic is Fragile
`extract_allowed_from_constraints()` attempts to parse allowed module names from free-text
constraint strings by splitting on whitespace and filtering import-related keywords. This is
brittle: a constraint like "Do not use external libraries" will parse "external" as an allowed
import. The rule engine will then allow `import external` in generated code.

### 5. No Cancellation Support
The VS Code extension sets `cancellable: false` on the progress notification. Long-running
generations (which can take 30+ seconds for 3-step workflows) cannot be interrupted by the user.

### 6. Exec-Based Test Execution Is Unsafe
`evaluate_functional_correctness()` in `evaluation.py` runs arbitrary generated code via
`exec()` with no sandboxing. This is only safe for controlled evaluation of trusted LLM output.

### 7. Token Count Is Always 0 in Evaluation Results
The `evaluation_results.json` shows `baseline_tokens: 0.0`. This is because `run_evaluation.py`
calls `generator.reset_token_count()` before each problem, but `evaluate_problem_baseline()`
calculates `tokens_used = generator.get_total_tokens() - tokens_before` — where `tokens_before`
is captured before the reset. If the reset happens before `tokens_before` is set, the diff will
be accurate. However, the database `save_evaluation_result()` records `total_tokens=0` for
baseline because the baseline `run_baseline_generation()` uses the correct token tracking. The
zero in the JSON suggests the token count mechanism works differently across the two code paths.
[NEEDS VERIFICATION with a live run]

### 8. No Streaming
Code is only available to the extension after the entire multi-step workflow completes. For a
3-step generation with corrections, this can be 30-60 seconds of a blank progress spinner.
Streaming intermediate steps via Server-Sent Events or WebSockets would significantly improve UX.

### 9. Python-Only Support
Both the generator system prompt and all validators assume Python. The AST validator explicitly
uses `ast.parse()` which is Python-only. There is no mechanism to detect or handle other
languages.

### 10. `user_feedback` Table Has No Write Path
The `user_feedback` table is defined in the database schema but `database.py` has no method
to insert into it, and no API endpoint accepts user feedback.

### 11. `generateBaseline` Is Unused in the Extension
`api.ts` exposes `generateBaseline()` but `extension.ts` never calls it. The extension only
surfaces the self-correcting generation path to users.

### 12. `agentState` Mutation Pattern
LangGraph nodes mutate the state dict in place and return it. This is the expected LangGraph
pattern but means each node must be careful not to accidentally share mutable references
(e.g., the `generated_steps` list is appended to rather than replaced).

---

## Environment Variables

| Variable | Required | Purpose |
|---|---|---|
| `GEMINI_API_KEY` | Yes | Google Generative AI API key for Gemini 1.5 Flash |
| `GROQ_API_KEY` | Yes | Groq API key for Llama 3.3 70B |
| `WANDB_API_KEY` | No | Weights and Biases API key for experiment tracking |

The backend loads `.env` from two locations (via two `load_dotenv()` calls in `models.py`):
the current working directory and the parent directory of `models.py`. Place `.env` at
the project root or in `backend/`.

---

## VS Code Extension Configuration

Users can configure the extension through VS Code Settings (`selfCorrectingAgent.*`):

| Setting | Default | Description |
|---|---|---|
| `selfCorrectingAgent.apiUrl` | `http://localhost:8000` | FastAPI backend URL |
| `selfCorrectingAgent.maxSteps` | `3` | Maximum generation steps (1-10) |

Note the casing mismatch: the setting is registered as `selfCorrectingAgent.apiUrl` in
`package.json` but read as `selfCorrectingAgent.apiUrl` via `config.get<string>('apiUrl')`.
VS Code normalizes this correctly, but the key names should be kept consistent.
