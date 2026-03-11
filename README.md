# Project Report: Self-Correcting IDE Agent

## 1. Executive Summary
The Self-Correcting IDE Agent is a sophisticated code generation system designed to minimize logical drift and semantic inconsistencies in AI-generated code. By employing a multi-agent orchestrated workflow, the system utilizes Google Gemini 1.5 Flash as the generative "Actor" and Groq Llama 3.3 70B as the analytic "Critic." The architecture ensures that every line of generated code is validated through deterministic AST checks, rule-based heuristics, and high-level LLM reasoning before finalization.

## 2. Technical Architecture
The system is built on a modular architecture comprising a localized IDE extension and a robust backend orchestration layer.

### 2.1 Backend Components
- **Orchestration Layer**: Utilizes LangGraph to manage the stateful transition between generation, validation, and potential regeneration cycles.
- **Generative Engine**: Google Gemini 1.5 Flash, configured with robust JSON parsing and error-handling capabilities to ensure consistent code output.
- **Validation Suite**: 
    - **AST Validator**: Performs syntax verification using Python's Abstract Syntax Tree module.
    - **Rule Engine**: enforces constraints regarding function signatures, unauthorized imports, and variable usage.
    - **LLM Critic**: Powered by Groq Llama 3.3 70B, providing deep semantic analysis of code logic against original task requirements.
- **Persistence Layer**: An SQLite database tracks every task, session, and validation step, providing a comprehensive audit trail for analysis.

### 2.2 Frontend Components
- **VS Code Extension**: Written in TypeScript, providing a seamless user interface via an Activity Bar icon and customizable keybindings (Ctrl+Shift+G).
- **Audit Interface**: A dedicated output channel displays real-time reasoning and drift detection results from the Critic.

## 3. Implementation Status

### 3.1 Completed Features
- **Stateless/Stateful Generation**: Support for both single-shot (baseline) and multi-step (self-correcting) generation workflows.
- **Robust Error Handling**: Implementation of quota management for Gemini Free Tier (automatic rate-limiting) and resilient JSON parsing logic.
- **Human Eval Pipeline**: A complete evaluation suite to benchmark the agent against the OpenAI HumanEval dataset, measuring Pass@1 accuracy, token efficiency, and latency.
- **Telemetry**: Optional integration with Weights & Biases for experiment tracking and metrics visualization.
- **Sidebar Integration**: Dedicated VS Code sidebar for easy access to generation controls and audit trails.

### 3.2 Roadmap (Future Work)
- **Multi-File Context**: Extending the Critic's awareness to include broader project context and cross-file dependencies.
- **Reinforcement Learning**: Implementing a feedback loop to optimize the Critic's judgment based on execution success rates.
- **Additional Language Support**: Expanding the validation rules and prompts to support JavaScript, TypeScript, and Go.
- **Streaming Generation**: Implementing real-time code streaming to improve UX during long generation tasks.

## 4. Installation and Setup

### 4.1 Prerequisites
- Python 3.10 or higher
- Node.js 18 or higher
- Valid API Keys for Google Gemini and Groq

### 4.2 Backend Configuration
1. Navigate to the backend directory:
   ```bash
   cd backend
   ```
2. Install Python dependencies:
   ```bash
   pip install -r requirements.txt
   ```
3. Configure environment variables in a `.env` file at the project root:
   ```env
   GEMINI_API_KEY=your_key_here
   GROQ_API_KEY=your_key_here
   WANDB_API_KEY=your_key_here (optional)
   ```
4. Initialize the server:
   ```bash
   python -m uvicorn main:app --reload --port 8000
   ```

### 4.3 VS Code Extension Setup
1. Navigate to the extension directory:
   ```bash
   cd vscode-extension
   ```
2. Install Node.js dependencies:
   ```bash
   npm install
   ```
3. Compile the extension:
   ```bash
   npm run compile
   ```
4. Open the project in VS Code and press `F5` to launch the "Extension Development Host."

## 5. Evaluation and Metrics
To verify the system's performance against the baseline, run the evaluation script:
```bash
cd backend
python run_evaluation.py --num-problems 10 --no-wandb
```
This utility generates a detailed `evaluation_results.json` file containing statistical analysis of accuracy and efficiency.

## 6. Audit Trail and Logging
Real-time reasoning logs can be viewed in the VS Code "Output" panel under the "Self-Correcting Agent" channel. This provides transparency into why the Critic flagged specific code segments for drift or inconsistency.
