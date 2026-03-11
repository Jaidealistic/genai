# Self-Correcting IDE Agent

A self-correcting code generation agent that uses **Gemini 1.5 Flash** as the Actor (code generator) and **Groq Llama 3.1 70B** as the Critic (drift detector). Built with LangGraph for orchestration and a VS Code extension as the IDE frontend.

## Architecture

```
VS Code Extension  →  FastAPI Backend  →  LangGraph Orchestrator
                                                ├── Gemini (Generate)
                                                ├── AST + Rules (Validate)
                                                ├── Groq/Llama (Critic)
                                                └── SQLite (State DB)
```

## Quick Start

### 1. Setup Environment

```bash
# Clone the repo
git clone https://github.com/Jaidealistic/genai.git
cd genai

# Copy and fill in API keys
cp .env.example .env
# Edit .env with your Gemini and Groq API keys
```

### 2. Install & Run Backend

```bash
cd backend
pip install -r requirements.txt
uvicorn main:app --reload --port 8000
```

The backend will be available at `http://localhost:8000`.

### 3. VS Code Extension (Optional)

```bash
cd vscode-extension
npm install
npm run compile
```

Then press `F5` in VS Code to launch with the extension, or use `Ctrl+Shift+G` to generate code.

### 4. Run Evaluation

```bash
cd backend
python run_evaluation.py --num-problems 10 --no-wandb
```

## API Endpoints

| Endpoint             | Method | Description                           |
| -------------------- | ------ | ------------------------------------- |
| `/generate`          | POST   | Generate code with self-correction    |
| `/generate/baseline` | POST   | Generate code without self-correction |
| `/health`            | GET    | Health check                          |

## Project Structure

```
genai/
├── backend/
│   ├── main.py              # FastAPI app
│   ├── orchestrator.py       # LangGraph workflow
│   ├── models.py             # Gemini + Groq clients
│   ├── validators.py         # AST + drift rules
│   ├── database.py           # SQLite operations
│   ├── evaluation.py         # HumanEval evaluation
│   ├── metrics.py            # Metrics & analysis
│   ├── run_evaluation.py     # Evaluation runner
│   └── requirements.txt
├── vscode-extension/
│   ├── package.json
│   ├── tsconfig.json
│   └── src/
│       ├── extension.ts      # VS Code entry point
│       └── api.ts            # Backend API client
├── .env.example
├── .gitignore
└── README.md
```

## Environment Variables

| Variable         | Required | Description                        |
| ---------------- | -------- | ---------------------------------- |
| `GEMINI_API_KEY` | Yes      | Google AI Studio API key           |
| `GROQ_API_KEY`   | Yes      | Groq console API key               |
| `WANDB_API_KEY`  | No       | Weights & Biases key (for logging) |
