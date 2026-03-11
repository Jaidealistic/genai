/**
 * FastAPI Client for the Self-Correcting IDE Agent.
 * Communicates with the backend to generate code.
 */

import axios, { AxiosInstance } from 'axios';

// ── Types ───────────────────────────────────────────────────────────────

export interface AuditEntry {
    step: number;
    action: string;
    drift_detected: boolean;
    explanation: string;
}

export interface GenerationResult {
    final_code: string;
    steps_count: number;
    corrections: number;
    tokens_used: number;
    execution_time: number;
    audit_trail: AuditEntry[];
    task_id?: string;
}

export interface GenerationRequest {
    prompt: string;
    constraints?: string[];
    max_steps?: number;
}

// ── API Client ──────────────────────────────────────────────────────────

export class AgentApiClient {
    private client: AxiosInstance;

    constructor(baseUrl: string = 'http://localhost:8000') {
        this.client = axios.create({
            baseURL: baseUrl,
            headers: { 'Content-Type': 'application/json' },
            timeout: 120000, // 2 minute timeout (generation can be slow)
        });
    }

    /**
     * Generate code with self-correcting drift detection.
     */
    async generateWithCorrection(request: GenerationRequest): Promise<GenerationResult> {
        const response = await this.client.post<GenerationResult>('/generate', {
            prompt: request.prompt,
            constraints: request.constraints || [],
            max_steps: request.max_steps || 3,
        });
        return response.data;
    }

    /**
     * Generate code without self-correction (baseline).
     */
    async generateBaseline(prompt: string, constraints: string[] = []): Promise<{
        final_code: string;
        tokens_used: number;
        execution_time: number;
    }> {
        const response = await this.client.post('/generate/baseline', {
            prompt,
            constraints,
        });
        return response.data;
    }

    /**
     * Check if the backend server is healthy.
     */
    async healthCheck(): Promise<boolean> {
        try {
            const response = await this.client.get('/health');
            return response.data?.status === 'healthy';
        } catch {
            return false;
        }
    }
}
