/**
 * Self-Correcting Code Agent - VS Code Extension
 *
 * Main entry point. Registers the code generation command and integrates
 * with the FastAPI backend for drift-detected code generation.
 */

import * as vscode from 'vscode';
import { AgentApiClient, GenerationResult } from './api';

let outputChannel: vscode.OutputChannel;

export function activate(context: vscode.ExtensionContext) {
    // Create output channel for audit trail
    outputChannel = vscode.window.createOutputChannel('Self-Correcting Agent');

    // Register the generate command
    const generateCommand = vscode.commands.registerCommand(
        'self-correcting-agent.generate',
        async () => {
            const editor = vscode.window.activeTextEditor;
            if (!editor) {
                vscode.window.showErrorMessage('No active editor. Open a file first.');
                return;
            }

            // Get configuration
            const config = vscode.workspace.getConfiguration('selfCorrectingAgent');
            const apiUrl = config.get<string>('apiUrl', 'http://localhost:8000');
            const maxSteps = config.get<number>('maxSteps', 3);

            const client = new AgentApiClient(apiUrl);

            // Check server health first
            const healthy = await client.healthCheck();
            if (!healthy) {
                const action = await vscode.window.showErrorMessage(
                    'Backend server is not running. Start the server first: cd backend && uvicorn main:app --port 8000',
                    'OK'
                );
                return;
            }

            // Get prompt from user
            const prompt = await vscode.window.showInputBox({
                prompt: 'Describe the Python code you want to generate',
                placeHolder: 'e.g., Write a function to calculate factorial recursively',
                ignoreFocusOut: true,
            });

            if (!prompt) {
                return; // User cancelled
            }

            // Optional: get constraints
            const constraintInput = await vscode.window.showInputBox({
                prompt: '(Optional) Enter constraints, comma-separated',
                placeHolder: 'e.g., No external libraries, Max complexity O(n)',
                ignoreFocusOut: true,
            });

            const constraints = constraintInput
                ? constraintInput.split(',').map(c => c.trim()).filter(c => c)
                : [];

            // Generate with progress indicator
            await vscode.window.withProgress(
                {
                    location: vscode.ProgressLocation.Notification,
                    title: 'Generating code with drift detection...',
                    cancellable: false,
                },
                async (progress) => {
                    try {
                        progress.report({ message: 'Sending to AI agent...' });

                        const result: GenerationResult = await client.generateWithCorrection({
                            prompt,
                            constraints,
                            max_steps: maxSteps,
                        });

                        // Insert generated code at cursor position
                        await editor.edit((editBuilder) => {
                            editBuilder.insert(
                                editor.selection.active,
                                result.final_code
                            );
                        });

                        // Show summary notification
                        const corrections = result.corrections > 0
                            ? ` (${result.corrections} drift corrections applied)`
                            : '';

                        vscode.window.showInformationMessage(
                            `Code generated in ${result.steps_count} steps${corrections} — ` +
                            `${result.tokens_used} tokens, ${result.execution_time}s`
                        );

                        // Show audit trail in output channel
                        showAuditTrail(result, prompt);

                    } catch (error: any) {
                        const message = error?.response?.data?.detail
                            || error?.message
                            || 'Unknown error';
                        vscode.window.showErrorMessage(
                            `Code generation failed: ${message}`
                        );
                        outputChannel.appendLine(`\n[ERROR] ${message}`);
                    }
                }
            );
        }
    );

    context.subscriptions.push(generateCommand);
    context.subscriptions.push(outputChannel);

    // Status bar item
    const statusBarItem = vscode.window.createStatusBarItem(
        vscode.StatusBarAlignment.Right, 100
    );
    statusBarItem.text = '$(hubot) AI Agent';
    statusBarItem.tooltip = 'Self-Correcting Code Agent';
    statusBarItem.command = 'self-correcting-agent.generate';
    statusBarItem.show();
    context.subscriptions.push(statusBarItem);
}

function showAuditTrail(result: GenerationResult, prompt: string) {
    outputChannel.clear();
    outputChannel.appendLine('═══════════════════════════════════════════');
    outputChannel.appendLine('  SELF-CORRECTING AGENT - Generation Report');
    outputChannel.appendLine('═══════════════════════════════════════════');
    outputChannel.appendLine('');
    outputChannel.appendLine(`  Prompt: ${prompt}`);
    outputChannel.appendLine(`  Steps: ${result.steps_count}`);
    outputChannel.appendLine(`  Corrections: ${result.corrections}`);
    outputChannel.appendLine(`  Tokens: ${result.tokens_used}`);
    outputChannel.appendLine(`  Time: ${result.execution_time}s`);
    outputChannel.appendLine('');

    if (result.audit_trail && result.audit_trail.length > 0) {
        outputChannel.appendLine('  ── Audit Trail ──');
        outputChannel.appendLine('');

        for (const entry of result.audit_trail) {
            const icon = entry.drift_detected ? '⚠️' : '✓';
            outputChannel.appendLine(
                `  ${icon} Step ${entry.step}: ${entry.action}`
            );
            if (entry.explanation) {
                outputChannel.appendLine(`     ${entry.explanation}`);
            }
        }
    }

    outputChannel.appendLine('');
    outputChannel.appendLine('═══════════════════════════════════════════');
    outputChannel.show(true); // Preserve focus on editor
}

export function deactivate() {
    // Cleanup
}
