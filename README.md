# Self-Correcting IDE Agent: Structural Drift Detection

## 1. Executive Summary
The Self-Correcting IDE Agent is a research prototype designed to minimize "logical drift" in AI-generated code. It utilizes a multi-agent orchestration pattern where a local **Actor** (Ollama llama3.2) generates code incrementally, while a high-reasoning **Critic** (Groq Llama 3.3 70B) validates each step. The system is integrated directly into VS Code, providing real-time audit trails of the agent's reasoning and self-correction cycles.

## 2. Technical Architecture
The system employs a "layered validation" strategy to ensure code quality and requirement adherence.

### 2.1 Layered Validation Pipeline
1. **AST Validator**: Deterministic syntax verification using Python's `ast` module.
2. **Rule Engine**: Heuristic checks for signature drift, unauthorized imports, and undefined variables.
3. **LLM Critic**: Semantic analysis powered by **Groq Llama 3.3 70B**, detecting subtle logical inconsistencies.

### 2.2 Core Components
- **Backend**: FastAPI server orchestrating the **LangGraph** workflow.
- **Actor (Generator)**: Local **Ollama llama3.2** for privacy and rapid iteration.
- **Persistence**: SQLite database (`agent_state.db`) tracking every generation step and validation result.
- **Frontend**: VS Code Extension (TypeScript) providing an Activity Bar interface and real-time reasoning logs.

## 3. Grading Quick Start (For Professor)

To evaluate the system quickly, follow these steps:

1. **Startup Backend**:
   ```bash
   cd backend
   # Ensure Ollama is running and Llama 3.2 is pulled: ollama pull llama3.2
   pip install -r requirements.txt
   python -m uvicorn main:app --reload
   ```
2. **Launch Extension**:
   - Open the `vscode-extension` folder in VS Code.
   - Press `F5` to start the Extension Development Host.
3. **Trigger Generation**:
   - In the new window, use `Ctrl+Shift+G` (or use the Sidebar icon).
   - Enter a prompt (e.g., "Create a data processing pipeline with error handling").
   - Watch the **Output Channel** ("Self-Correcting Agent") for real-time drift detection logs.

## 4. Installation and Setup

### 4.1 Prerequisites
- **Python 3.10+**
- **Node.js 18+**
- **Ollama** (running locally with `llama3.2` pulled)
- **Groq API Key** (Set in `.env` at project root)

### 4.2 Backend Configuration
1. Navigate to `backend/`.
2. Create a `.env` file (or use the one in root) with:
   ```env
   GROQ_API_KEY=your_key_here
   ```
3. Initialize the server:
   ```bash
   python -m uvicorn main:app --port 8000
   ```

### 4.3 VS Code Extension Setup
1. Navigate to `vscode-extension/`.
2. `npm install` && `npm run compile`.
3. Launch via `F5` or install the generated `.vsix`.

## 5. Evaluation and Metrics
The system includes a benchmarking suite against the **OpenAI HumanEval** dataset.
```bash
cd backend
python run_evaluation.py --num-problems 5 --no-wandb
```
This generates `evaluation_results.json`, comparing the self-correcting system against a vanilla baseline.

## 6. Audit Trail and Logging
Reasoning logs are streamed to the VS Code **Output** panel. The system explicitly logs:
- **[Generated]**: Initial code chunk.
- **[Critic Detected Drift]**: Explanation of why the code deviated from requirements.
- **[Regenerated]**: The agent's attempt to fix its own logic.
- **[Validated]**: Final acceptance of the code chunk.
