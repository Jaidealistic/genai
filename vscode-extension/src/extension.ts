/**
 * Self-Correcting Code Agent - VS Code Extension
 *
 * Main entry point. Provides a WebView-based panel for code generation
 * with real-time step progress, drift detection display, and code preview.
 */

import * as vscode from 'vscode';
import { AgentApiClient, GenerationResult } from './api';

let outputChannel: vscode.OutputChannel;
let agentPanel: vscode.WebviewPanel | undefined;
let statusBarItem: vscode.StatusBarItem;

// ── Activate ──────────────────────────────────────────────────────────────

export function activate(context: vscode.ExtensionContext) {
    outputChannel = vscode.window.createOutputChannel('Self-Correcting Agent');

    // Status bar item
    statusBarItem = vscode.window.createStatusBarItem(vscode.StatusBarAlignment.Right, 100);
    statusBarItem.text = '$(hubot) AI Agent';
    statusBarItem.tooltip = 'Self-Correcting Code Agent — Click to open';
    statusBarItem.command = 'self-correcting-agent.openPanel';
    statusBarItem.show();

    // Commands
    const openPanelCmd = vscode.commands.registerCommand(
        'self-correcting-agent.openPanel',
        () => openAgentPanel(context)
    );

    // Keep old generate command pointing at the panel
    const generateCmd = vscode.commands.registerCommand(
        'self-correcting-agent.generate',
        () => openAgentPanel(context)
    );

    context.subscriptions.push(openPanelCmd, generateCmd, statusBarItem, outputChannel);

    // Sidebar tree view
    vscode.window.registerTreeDataProvider(
        'self-correcting-agent-view',
        new AgentViewProvider()
    );

    // Periodic health check (every 30s)
    checkServerHealth(context);
    const healthTimer = setInterval(() => checkServerHealth(context), 30_000);
    context.subscriptions.push({ dispose: () => clearInterval(healthTimer) });
}

// ── Health check ──────────────────────────────────────────────────────────

async function checkServerHealth(context: vscode.ExtensionContext) {
    const config = vscode.workspace.getConfiguration('selfCorrectingAgent');
    const apiUrl = config.get<string>('apiUrl', 'http://localhost:8000');
    const client = new AgentApiClient(apiUrl);
    const healthy = await client.healthCheck();

    // Update status bar
    if (healthy) {
        statusBarItem.text = '$(hubot) AI Agent $(check)';
        statusBarItem.tooltip = 'Self-Correcting Agent — Backend connected. Click to open.';
    } else {
        statusBarItem.text = '$(hubot) AI Agent $(warning)';
        statusBarItem.tooltip = 'Self-Correcting Agent — Backend offline. Click to open.';
    }

    // Notify the panel if it is open
    if (agentPanel) {
        agentPanel.webview.postMessage({ type: 'serverStatus', healthy });
    }
}

// ── WebView Panel ─────────────────────────────────────────────────────────

function openAgentPanel(context: vscode.ExtensionContext) {
    // Reuse existing panel if open
    if (agentPanel) {
        agentPanel.reveal(vscode.ViewColumn.Beside);
        return;
    }

    const config = vscode.workspace.getConfiguration('selfCorrectingAgent');
    const apiUrl = config.get<string>('apiUrl', 'http://localhost:8000');
    const maxSteps = config.get<number>('maxSteps', 3);

    agentPanel = vscode.window.createWebviewPanel(
        'selfCorrectingAgent',
        'Self-Correcting Agent',
        vscode.ViewColumn.Beside,
        { enableScripts: true, retainContextWhenHidden: true }
    );

    agentPanel.webview.html = getWebviewContent({ apiUrl, maxSteps });

    // Send initial health status
    const client = new AgentApiClient(apiUrl);
    client.healthCheck().then(healthy => {
        agentPanel?.webview.postMessage({ type: 'serverStatus', healthy });
    });

    // Handle messages from WebView
    agentPanel.webview.onDidReceiveMessage(
        async (message) => {
            switch (message.type) {
                case 'generate':
                    await handleGenerate(message, apiUrl, maxSteps);
                    break;

                case 'insert':
                    await insertCodeAtCursor(message.code);
                    break;

                case 'openNewFile':
                    await openCodeInNewFile(message.code);
                    break;

                case 'checkHealth':
                    const healthy = await client.healthCheck();
                    agentPanel?.webview.postMessage({ type: 'serverStatus', healthy });
                    break;
            }
        },
        undefined,
        context.subscriptions
    );

    agentPanel.onDidDispose(() => {
        agentPanel = undefined;
    });
}

async function handleGenerate(
    message: { prompt: string; constraints: string[]; maxSteps: number },
    apiUrl: string,
    defaultMaxSteps: number
) {
    const client = new AgentApiClient(apiUrl);

    // Verify server is up before sending
    const healthy = await client.healthCheck();
    if (!healthy) {
        agentPanel?.webview.postMessage({
            type: 'error',
            message: 'Backend server is not running.\n\nStart it with:\n  cd backend\n  uvicorn main:app --port 8000',
        });
        return;
    }

    try {
        const result: GenerationResult = await client.generateWithCorrection({
            prompt: message.prompt,
            constraints: message.constraints,
            max_steps: message.maxSteps || defaultMaxSteps,
        });

        agentPanel?.webview.postMessage({ type: 'result', result });

        // Also write audit trail to output channel
        writeAuditTrail(result, message.prompt);

    } catch (error: any) {
        const msg = error?.response?.data?.detail || error?.message || 'Unknown error';
        agentPanel?.webview.postMessage({ type: 'error', message: msg });
        outputChannel.appendLine(`\n[ERROR] ${msg}`);
    }
}

async function insertCodeAtCursor(code: string) {
    const editor = vscode.window.activeTextEditor;
    if (!editor) {
        vscode.window.showErrorMessage('No active editor. Open a file and place your cursor where you want the code inserted.');
        return;
    }
    await editor.edit((eb) => eb.insert(editor.selection.active, code));
    vscode.window.showInformationMessage('Code inserted at cursor position.');
}

async function openCodeInNewFile(code: string) {
    const doc = await vscode.workspace.openTextDocument({
        content: code,
        language: 'python',
    });
    await vscode.window.showTextDocument(doc, vscode.ViewColumn.Active);
}

// ── Sidebar ───────────────────────────────────────────────────────────────

class AgentViewProvider implements vscode.TreeDataProvider<vscode.TreeItem> {
    getTreeItem(element: vscode.TreeItem): vscode.TreeItem {
        return element;
    }

    getChildren(element?: vscode.TreeItem): Thenable<vscode.TreeItem[]> {
        if (element) { return Promise.resolve([]); }

        const generateItem = new vscode.TreeItem('Generate Code with AI', vscode.TreeItemCollapsibleState.None);
        generateItem.command = { command: 'self-correcting-agent.openPanel', title: 'Open Agent Panel' };
        generateItem.iconPath = new vscode.ThemeIcon('add');
        generateItem.tooltip = 'Open the code generation panel';

        const outputItem = new vscode.TreeItem('View Last Audit Trail', vscode.TreeItemCollapsibleState.None);
        outputItem.command = { command: 'workbench.action.output.toggleOutput', title: 'View Output' };
        outputItem.iconPath = new vscode.ThemeIcon('list-unordered');
        outputItem.tooltip = 'See the step-by-step reasoning from the last generation';

        return Promise.resolve([generateItem, outputItem]);
    }
}

// ── Audit trail output channel ────────────────────────────────────────────

function writeAuditTrail(result: GenerationResult, prompt: string) {
    outputChannel.clear();
    outputChannel.appendLine('═══════════════════════════════════════════');
    outputChannel.appendLine('  SELF-CORRECTING AGENT — Generation Report');
    outputChannel.appendLine('═══════════════════════════════════════════');
    outputChannel.appendLine('');
    outputChannel.appendLine(`  Prompt    : ${prompt}`);
    outputChannel.appendLine(`  Steps     : ${result.steps_count}`);
    outputChannel.appendLine(`  Corrections: ${result.corrections}`);
    outputChannel.appendLine(`  Tokens    : ${result.tokens_used}`);
    outputChannel.appendLine(`  Time      : ${result.execution_time}s`);
    outputChannel.appendLine('');

    if (result.audit_trail?.length) {
        outputChannel.appendLine('  ── Audit Trail ──');
        outputChannel.appendLine('');
        for (const entry of result.audit_trail) {
            const icon = entry.drift_detected ? '[DRIFT]' : '[  OK ]';
            outputChannel.appendLine(`  ${icon}  Step ${entry.step} · ${entry.action}`);
            if (entry.explanation) {
                outputChannel.appendLine(`           ${entry.explanation}`);
            }
        }
    }

    outputChannel.appendLine('');
    outputChannel.appendLine('═══════════════════════════════════════════');
    outputChannel.show(true);
}

// ── WebView HTML ──────────────────────────────────────────────────────────

function getWebviewContent(config: { apiUrl: string; maxSteps: number }): string {
    return /* html */ `<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Self-Correcting Agent</title>
<style>
  :root {
    --bg: var(--vscode-editor-background);
    --text: var(--vscode-editor-foreground);
    --muted: var(--vscode-descriptionForeground);
    --border: var(--vscode-panel-border, rgba(128,128,128,0.25));
    --input-bg: var(--vscode-input-background);
    --input-text: var(--vscode-input-foreground);
    --input-border: var(--vscode-input-border, rgba(128,128,128,0.4));
    --btn-bg: var(--vscode-button-background);
    --btn-text: var(--vscode-button-foreground);
    --btn2-bg: var(--vscode-button-secondaryBackground);
    --btn2-text: var(--vscode-button-secondaryForeground);
    --badge-bg: var(--vscode-badge-background);
    --badge-text: var(--vscode-badge-foreground);
    --code-bg: var(--vscode-textCodeBlock-background, rgba(0,0,0,0.2));
    --focus: var(--vscode-focusBorder);
    --selection-bg: var(--vscode-editor-inactiveSelectionBackground);
  }
  *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
  body {
    font-family: var(--vscode-font-family);
    font-size: var(--vscode-font-size, 13px);
    color: var(--text);
    background: var(--bg);
    padding: 20px 18px;
    line-height: 1.55;
  }

  /* Screens */
  .screen { display: none; }
  .screen.active { display: block; }

  /* Typography */
  .page-title {
    font-size: 15px;
    font-weight: 700;
    display: flex;
    align-items: center;
    gap: 8px;
    margin-bottom: 14px;
  }
  .section-label {
    font-size: 10px;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.6px;
    color: var(--muted);
    margin: 16px 0 6px;
  }

  /* Badges */
  .badge {
    display: inline-flex;
    align-items: center;
    gap: 5px;
    font-size: 11px;
    font-weight: 600;
    padding: 3px 9px;
    border-radius: 10px;
    margin-bottom: 14px;
  }
  .badge-dot { width: 7px; height: 7px; border-radius: 50%; }
  .badge-green { background: rgba(72,196,72,0.12); color: #48c448; }
  .badge-green .badge-dot { background: #48c448; }
  .badge-red   { background: rgba(220,60,60,0.12); color: #dc4040; }
  .badge-red   .badge-dot { background: #dc4040; animation: blink 1.2s step-end infinite; }
  .badge-yellow{ background: rgba(200,180,0,0.12); color: #c0a800; }
  .badge-yellow .badge-dot { background: #c0a800; }
  @keyframes blink { 50% { opacity: 0; } }

  /* Form */
  .form-group { margin-bottom: 14px; }
  label {
    display: block;
    font-size: 11px;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.5px;
    color: var(--muted);
    margin-bottom: 6px;
  }
  textarea, input[type="text"] {
    width: 100%;
    background: var(--input-bg);
    color: var(--input-text);
    border: 1px solid var(--input-border);
    border-radius: 3px;
    padding: 8px 10px;
    font-family: inherit;
    font-size: inherit;
    resize: vertical;
    outline: none;
  }
  textarea:focus, input[type="text"]:focus {
    border-color: var(--focus);
  }
  textarea { min-height: 80px; }

  .slider-row { display: flex; align-items: center; gap: 10px; }
  input[type="range"] { flex: 1; accent-color: var(--btn-bg); cursor: pointer; }
  .slider-val { font-size: 14px; font-weight: 700; min-width: 22px; text-align: center; }
  .helper { font-size: 11px; color: var(--muted); margin-top: 4px; }

  /* Buttons */
  .btn-row { display: flex; gap: 8px; flex-wrap: wrap; margin-top: 14px; }
  button {
    background: var(--btn-bg);
    color: var(--btn-text);
    border: none;
    border-radius: 3px;
    padding: 7px 14px;
    font-size: 12px;
    font-family: inherit;
    cursor: pointer;
    display: inline-flex;
    align-items: center;
    gap: 5px;
  }
  button:hover { opacity: 0.88; }
  button:active { opacity: 0.75; }
  button:disabled { opacity: 0.4; cursor: not-allowed; }
  .btn-secondary { background: var(--btn2-bg); color: var(--btn2-text); }

  /* ── Loading screen ── */
  .loading-center {
    text-align: center;
    padding: 20px 0 12px;
  }
  .spinner {
    width: 30px; height: 30px;
    border: 3px solid rgba(128,128,128,0.15);
    border-top-color: var(--btn-bg);
    border-radius: 50%;
    animation: spin 0.75s linear infinite;
    margin: 0 auto 10px;
  }
  @keyframes spin { to { transform: rotate(360deg); } }
  .loading-prompt-preview {
    font-size: 11px;
    color: var(--muted);
    margin-top: 4px;
    font-style: italic;
  }

  .steps-track { margin: 14px 0; }
  .step-row {
    display: flex;
    align-items: flex-start;
    gap: 12px;
    padding: 9px 0;
    border-bottom: 1px solid var(--border);
    opacity: 0.35;
    transition: opacity 0.25s;
  }
  .step-row.active  { opacity: 1; }
  .step-row.done    { opacity: 0.85; }

  .step-num {
    width: 26px; height: 26px;
    border-radius: 50%;
    background: var(--badge-bg);
    color: var(--badge-text);
    display: flex; align-items: center; justify-content: center;
    font-size: 11px; font-weight: 700;
    flex-shrink: 0;
    margin-top: 1px;
    transition: background 0.2s, color 0.2s;
  }
  .step-num.active  { background: var(--btn-bg); color: var(--btn-text); animation: pulse 1.1s ease-in-out infinite; }
  .step-num.valid   { background: #3d9e3d; color: #fff; }
  .step-num.drift   { background: #c93a3a; color: #fff; }
  .step-num.corrected { background: #9a7c00; color: #fff; }
  @keyframes pulse { 0%,100% { transform: scale(1); } 50% { transform: scale(1.12); } }

  .step-info { flex: 1; min-width: 0; }
  .step-title { font-size: 13px; font-weight: 600; }
  .step-detail { font-size: 11px; color: var(--muted); margin-top: 2px; }

  .loading-note {
    font-size: 11px;
    color: var(--muted);
    text-align: center;
    margin-top: 14px;
  }

  /* ── Results screen ── */
  .stats-grid {
    display: grid;
    grid-template-columns: repeat(4, 1fr);
    gap: 8px;
    margin: 12px 0 14px;
  }
  .stat-box {
    background: var(--selection-bg);
    border-radius: 4px;
    padding: 10px;
    text-align: center;
  }
  .stat-val { font-size: 20px; font-weight: 800; }
  .stat-lbl { font-size: 9px; text-transform: uppercase; letter-spacing: 0.5px; color: var(--muted); margin-top: 3px; }

  .banner {
    border-radius: 4px;
    padding: 9px 12px;
    margin: 10px 0;
    font-size: 12px;
    display: flex;
    align-items: center;
    gap: 8px;
  }
  .banner-warn  { background: rgba(200,60,0,0.1);  border: 1px solid rgba(200,60,0,0.3); }
  .banner-clean { background: rgba(60,200,60,0.08); border: 1px solid rgba(60,200,60,0.2); }

  .code-block {
    background: var(--code-bg);
    border: 1px solid var(--border);
    border-radius: 4px;
    padding: 12px;
    font-family: var(--vscode-editor-font-family, 'Courier New', monospace);
    font-size: 12px;
    white-space: pre;
    overflow-x: auto;
    max-height: 320px;
    overflow-y: auto;
    margin: 8px 0;
    tab-size: 4;
  }

  /* Audit trail */
  .audit-entry {
    display: flex;
    gap: 10px;
    padding: 7px 0;
    border-bottom: 1px solid rgba(128,128,128,0.1);
    font-size: 12px;
  }
  .audit-icon { flex-shrink: 0; font-size: 13px; margin-top: 1px; }
  .audit-action {
    font-size: 10px;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.4px;
    color: var(--muted);
  }
  .audit-explanation { margin-top: 2px; color: var(--text); }
  .audit-drift .audit-action { color: #c93a3a; }
  .audit-corrected .audit-action { color: #9a7c00; }

  /* Error screen */
  .error-box {
    background: rgba(200,50,50,0.1);
    border: 1px solid rgba(200,50,50,0.3);
    border-radius: 4px;
    padding: 12px;
    font-size: 12px;
    white-space: pre-wrap;
    margin: 12px 0;
    font-family: var(--vscode-editor-font-family, monospace);
  }

  hr { border: none; border-top: 1px solid var(--border); margin: 16px 0; }
</style>
</head>
<body>

<!-- ═══ SCREEN: Form ═══ -->
<div class="screen active" id="screen-form">
  <div class="page-title">🤖 Self-Correcting Code Agent</div>

  <div id="server-badge" class="badge badge-yellow">
    <span class="badge-dot"></span> Checking server…
  </div>

  <div class="form-group">
    <label>What code do you want to generate?</label>
    <textarea id="inp-prompt" rows="4"
      placeholder="e.g., Write a Python function to parse a CSV file and return a list of dicts, handling missing values gracefully"></textarea>
  </div>

  <div class="form-group">
    <label>Constraints <span style="font-weight:400;text-transform:none;">(optional, comma-separated)</span></label>
    <input type="text" id="inp-constraints"
      placeholder="e.g., No external libraries, add type hints, handle None values">
  </div>

  <div class="form-group">
    <label>Generation Steps</label>
    <div class="slider-row">
      <input type="range" id="inp-steps" min="1" max="10" value="${config.maxSteps}">
      <span class="slider-val" id="steps-label">${config.maxSteps}</span>
    </div>
    <div class="helper">More steps = more thorough code, but takes longer (~15s per step)</div>
  </div>

  <div class="btn-row">
    <button id="btn-generate" onclick="startGeneration()">⚡ Generate with Self-Correction</button>
    <button class="btn-secondary" onclick="checkHealth()">↻ Check Server</button>
  </div>
</div>

<!-- ═══ SCREEN: Loading ═══ -->
<div class="screen" id="screen-loading">
  <div class="loading-center">
    <div class="spinner"></div>
    <div style="font-weight:700;font-size:13px;">Generating &amp; validating for drift…</div>
    <div class="loading-prompt-preview" id="loading-preview"></div>
  </div>

  <div class="steps-track" id="steps-track"></div>

  <p class="loading-note">
    Each step is validated with AST analysis, rule checks, and an LLM critic.<br>
    Drift is corrected automatically before moving to the next step.
  </p>
</div>

<!-- ═══ SCREEN: Results ═══ -->
<div class="screen" id="screen-results">
  <div class="page-title" id="result-title">✅ Generation Complete</div>

  <div class="stats-grid">
    <div class="stat-box"><div class="stat-val" id="s-steps">—</div><div class="stat-lbl">Steps</div></div>
    <div class="stat-box"><div class="stat-val" id="s-corrections">—</div><div class="stat-lbl">Corrections</div></div>
    <div class="stat-box"><div class="stat-val" id="s-tokens">—</div><div class="stat-lbl">Tokens</div></div>
    <div class="stat-box"><div class="stat-val" id="s-time">—</div><div class="stat-lbl">Seconds</div></div>
  </div>

  <div id="drift-banner"></div>

  <div class="section-label">Generated Code</div>
  <div class="code-block" id="code-output"></div>

  <div class="btn-row">
    <button onclick="sendInsert()">↩ Insert at Cursor</button>
    <button class="btn-secondary" onclick="sendOpenFile()">📄 Open in New File</button>
    <button class="btn-secondary" onclick="showForm()">← Generate Again</button>
  </div>

  <hr>
  <div class="section-label">Audit Trail</div>
  <div id="audit-trail"></div>
</div>

<!-- ═══ SCREEN: Error ═══ -->
<div class="screen" id="screen-error">
  <div class="page-title">❌ Generation Failed</div>
  <div class="error-box" id="err-msg"></div>
  <div class="btn-row">
    <button onclick="showForm()">← Try Again</button>
  </div>
</div>

<script>
  const vscode = acquireVsCodeApi();
  let lastResult = null;
  let animTimers = [];

  // ── Slider ──
  const slider = document.getElementById('inp-steps');
  const sliderLabel = document.getElementById('steps-label');
  slider.addEventListener('input', () => { sliderLabel.textContent = slider.value; });

  // ── Screen navigation ──
  function showScreen(id) {
    document.querySelectorAll('.screen').forEach(s => s.classList.remove('active'));
    document.getElementById(id).classList.add('active');
  }
  function showForm() { showScreen('screen-form'); }

  // ── Health check ──
  function checkHealth() { vscode.postMessage({ type: 'checkHealth' }); }

  // ── Generation ──
  function startGeneration() {
    const prompt = document.getElementById('inp-prompt').value.trim();
    if (!prompt) {
      document.getElementById('inp-prompt').style.borderColor = 'var(--vscode-inputValidation-errorBorder, #c93a3a)';
      document.getElementById('inp-prompt').focus();
      return;
    }
    document.getElementById('inp-prompt').style.borderColor = '';

    const constraints = document.getElementById('inp-constraints').value
      .split(',').map(s => s.trim()).filter(Boolean);
    const maxSteps = parseInt(slider.value, 10);

    // Build step track
    buildStepTrack(maxSteps);
    document.getElementById('loading-preview').textContent =
      prompt.length > 72 ? prompt.slice(0, 72) + '…' : prompt;

    showScreen('screen-loading');
    animateSteps(maxSteps);

    vscode.postMessage({ type: 'generate', prompt, constraints, maxSteps });
  }

  // ── Build loading step track ──
  function buildStepTrack(total) {
    const track = document.getElementById('steps-track');
    track.innerHTML = '';
    for (let i = 1; i <= total; i++) {
      track.insertAdjacentHTML('beforeend', \`
        <div class="step-row" id="sr-\${i}">
          <div class="step-num" id="sn-\${i}">\${i}</div>
          <div class="step-info">
            <div class="step-title">Step \${i}</div>
            <div class="step-detail" id="sd-\${i}">Waiting…</div>
          </div>
        </div>\`);
    }
  }

  // ── Speculative step animation ──
  function animateSteps(total) {
    animTimers.forEach(clearTimeout);
    animTimers = [];
    const perStep = 15_000; // ~15s per step estimate
    for (let i = 1; i <= total; i++) {
      const base = (i - 1) * perStep;
      animTimers.push(setTimeout(() => {
        setStepState(i, 'active', 'Generating code…');
      }, base));
      animTimers.push(setTimeout(() => {
        setStepState(i, 'active', 'Running validation (AST + rules + LLM critic)…');
      }, base + 8_000));
    }
  }

  function setStepState(i, cls, detail) {
    const row = document.getElementById('sr-' + i);
    const num = document.getElementById('sn-' + i);
    const det = document.getElementById('sd-' + i);
    if (!row) return;
    row.className = 'step-row ' + cls;
    num.className = 'step-num ' + cls;
    if (det && detail) det.textContent = detail;
  }

  // ── Render results ──
  function renderResults(result) {
    lastResult = result;

    // Stop animations
    animTimers.forEach(clearTimeout);

    // Update step track from audit trail
    const stepMap = {};
    for (const e of (result.audit_trail || [])) {
      (stepMap[e.step] = stepMap[e.step] || []).push(e);
    }
    for (const [step, entries] of Object.entries(stepMap)) {
      const hasDrift   = entries.some(e => e.drift_detected);
      const hasFix     = entries.some(e => e.action === 'regenerated');
      if (hasDrift && !hasFix) {
        setStepState(step, 'done', 'Drift detected (max corrections reached)');
        document.getElementById('sn-' + step).className = 'step-num drift';
        document.getElementById('sn-' + step).textContent = '✗';
      } else if (hasDrift && hasFix) {
        setStepState(step, 'done', 'Drift detected → corrected');
        document.getElementById('sn-' + step).className = 'step-num corrected';
        document.getElementById('sn-' + step).textContent = '⟳';
      } else {
        setStepState(step, 'done', 'Validated clean');
        document.getElementById('sn-' + step).className = 'step-num valid';
        document.getElementById('sn-' + step).textContent = '✓';
      }
    }

    // Stats
    document.getElementById('s-steps').textContent       = result.steps_count;
    document.getElementById('s-corrections').textContent = result.corrections;
    document.getElementById('s-tokens').textContent      = result.tokens_used;
    document.getElementById('s-time').textContent        = result.execution_time + 's';

    // Drift banner
    const banner = document.getElementById('drift-banner');
    if (result.corrections > 0) {
      banner.innerHTML = \`<div class="banner banner-warn">⚠️ \${result.corrections} logic drift correction\${result.corrections > 1 ? 's' : ''} applied automatically</div>\`;
    } else {
      banner.innerHTML = \`<div class="banner banner-clean">✓ No logic drift detected — all steps passed validation</div>\`;
    }

    // Code
    document.getElementById('code-output').textContent = result.final_code;

    // Audit trail
    const auditEl = document.getElementById('audit-trail');
    auditEl.innerHTML = '';
    for (const entry of (result.audit_trail || [])) {
      const cls = entry.drift_detected
        ? (entry.action === 'regenerated' ? 'audit-corrected' : 'audit-drift')
        : '';
      const icon = entry.drift_detected ? '⚠' : '✓';
      const actionLabel = entry.action.replace(/_/g, ' ');
      auditEl.insertAdjacentHTML('beforeend', \`
        <div class="audit-entry \${cls}">
          <span class="audit-icon">\${icon}</span>
          <div>
            <div class="audit-action">Step \${entry.step} · \${actionLabel}</div>
            <div class="audit-explanation">\${entry.explanation || ''}</div>
          </div>
        </div>\`);
    }

    showScreen('screen-results');
  }

  // ── Code actions ──
  function sendInsert()   { if (lastResult) vscode.postMessage({ type: 'insert',      code: lastResult.final_code }); }
  function sendOpenFile() { if (lastResult) vscode.postMessage({ type: 'openNewFile', code: lastResult.final_code }); }

  // ── Extension → WebView messages ──
  window.addEventListener('message', ({ data }) => {
    if (data.type === 'serverStatus') {
      const badge = document.getElementById('server-badge');
      const btn   = document.getElementById('btn-generate');
      if (data.healthy) {
        badge.className = 'badge badge-green';
        badge.innerHTML = '<span class="badge-dot"></span> Backend connected';
        if (btn) btn.disabled = false;
      } else {
        badge.className = 'badge badge-red';
        badge.innerHTML = '<span class="badge-dot"></span> Backend offline — run: cd backend && uvicorn main:app --port 8000';
        if (btn) btn.disabled = true;
      }
    }
    if (data.type === 'result') { renderResults(data.result); }
    if (data.type === 'error')  {
      document.getElementById('err-msg').textContent = data.message;
      showScreen('screen-error');
    }
  });
</script>
</body>
</html>`;
}

export function deactivate() { /* cleanup handled via subscriptions */ }
