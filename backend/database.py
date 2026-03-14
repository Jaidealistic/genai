"""
SQLite State Database for the Self-Correcting IDE Agent.
Stores tasks, generation sessions, steps, validations, regenerations, and evaluation results.
"""

import sqlite3
import json
from datetime import datetime
from typing import List, Optional


class StateDatabase:
    """Manages SQLite state persistence for the agent workflow."""

    def __init__(self, db_path: str = "agent_state.db"):
        self.db_path = db_path
        self.conn = sqlite3.connect(db_path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.cursor = self.conn.cursor()
        self._create_tables()

    def _create_tables(self):
        """Create all required tables and indexes."""
        self.cursor.executescript("""
            -- Main task metadata
            CREATE TABLE IF NOT EXISTS tasks (
                task_id TEXT PRIMARY KEY,
                prompt TEXT NOT NULL,
                function_signature TEXT,
                constraints TEXT,
                test_suite TEXT,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            );

            -- Generation sessions
            CREATE TABLE IF NOT EXISTS generation_sessions (
                session_id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_id TEXT NOT NULL,
                system_type TEXT NOT NULL,
                model_generator TEXT,
                model_critic TEXT,
                start_time DATETIME DEFAULT CURRENT_TIMESTAMP,
                end_time DATETIME,
                status TEXT DEFAULT 'in_progress',
                FOREIGN KEY (task_id) REFERENCES tasks(task_id)
            );

            -- Individual generation steps
            CREATE TABLE IF NOT EXISTS generation_steps (
                step_id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id INTEGER NOT NULL,
                step_number INTEGER NOT NULL,
                code TEXT NOT NULL,
                reasoning TEXT,
                addresses_requirement TEXT,
                assumptions TEXT,
                validation_status TEXT DEFAULT 'pending',
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (session_id) REFERENCES generation_sessions(session_id)
            );

            -- Validation results
            CREATE TABLE IF NOT EXISTS validations (
                validation_id INTEGER PRIMARY KEY AUTOINCREMENT,
                step_id INTEGER NOT NULL,
                validator_type TEXT NOT NULL,
                passed BOOLEAN NOT NULL,
                confidence_score REAL,
                feedback TEXT,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (step_id) REFERENCES generation_steps(step_id)
            );

            -- Regeneration attempts
            CREATE TABLE IF NOT EXISTS regenerations (
                regeneration_id INTEGER PRIMARY KEY AUTOINCREMENT,
                original_step_id INTEGER NOT NULL,
                attempt_number INTEGER NOT NULL,
                corrective_prompt TEXT,
                regenerated_code TEXT,
                succeeded BOOLEAN,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (original_step_id) REFERENCES generation_steps(step_id)
            );

            -- Final results
            CREATE TABLE IF NOT EXISTS evaluation_results (
                result_id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id INTEGER NOT NULL,
                final_code TEXT,
                tests_passed INTEGER,
                tests_total INTEGER,
                total_tokens INTEGER,
                total_corrections INTEGER,
                execution_time_seconds REAL,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (session_id) REFERENCES generation_sessions(session_id)
            );

            -- User feedback
            CREATE TABLE IF NOT EXISTS user_feedback (
                feedback_id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id INTEGER NOT NULL,
                rating INTEGER,
                comments TEXT,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (session_id) REFERENCES generation_sessions(session_id)
            );

            -- Indexes
            CREATE INDEX IF NOT EXISTS idx_sessions_task ON generation_sessions(task_id);
            CREATE INDEX IF NOT EXISTS idx_steps_session ON generation_steps(session_id);
            CREATE INDEX IF NOT EXISTS idx_validations_step ON validations(step_id);
        """)
        self.conn.commit()

    # ── Task Operations ──────────────────────────────────────────────────

    def create_task(self, task_id: str, prompt: str,
                    function_signature: str = None,
                    constraints: list = None,
                    test_suite: list = None) -> str:
        """Create a new task entry."""
        self.cursor.execute("""
            INSERT OR REPLACE INTO tasks (task_id, prompt, function_signature, constraints, test_suite)
            VALUES (?, ?, ?, ?, ?)
        """, (
            task_id, prompt, function_signature,
            json.dumps(constraints or []),
            json.dumps(test_suite or [])
        ))
        self.conn.commit()
        return task_id

    def get_task(self, task_id: str) -> Optional[dict]:
        """Retrieve a task by ID."""
        self.cursor.execute("SELECT * FROM tasks WHERE task_id = ?", (task_id,))
        row = self.cursor.fetchone()
        if row:
            result = dict(row)
            result['constraints'] = json.loads(result['constraints'] or '[]')
            result['test_suite'] = json.loads(result['test_suite'] or '[]')
            return result
        return None

    # ── Session Operations ───────────────────────────────────────────────

    def create_session(self, task_id: str, system_type: str,
                       model_generator: str = "llama3.2",
                       model_critic: str = "llama-3.3-70b-versatile") -> int:
        """Create a new generation session."""
        self.cursor.execute("""
            INSERT INTO generation_sessions (task_id, system_type, model_generator, model_critic, status)
            VALUES (?, ?, ?, ?, 'in_progress')
        """, (task_id, system_type, model_generator, model_critic))
        self.conn.commit()
        return self.cursor.lastrowid

    def complete_session(self, session_id: int, status: str = "completed"):
        """Mark a session as completed or failed."""
        self.cursor.execute("""
            UPDATE generation_sessions SET end_time = ?, status = ?
            WHERE session_id = ?
        """, (datetime.now().isoformat(), status, session_id))
        self.conn.commit()

    # ── Step Operations ──────────────────────────────────────────────────

    def save_step(self, session_id: int, step_data: dict) -> int:
        """Save a generated code step."""
        self.cursor.execute("""
            INSERT INTO generation_steps
            (session_id, step_number, code, reasoning, addresses_requirement, assumptions)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (
            session_id,
            step_data.get('step_number', 1),
            step_data.get('code', ''),
            step_data.get('reasoning', ''),
            step_data.get('addresses_requirement', ''),
            json.dumps(step_data.get('assumptions', []))
        ))
        self.conn.commit()
        return self.cursor.lastrowid

    def update_step_status(self, step_id: int, status: str):
        """Update validation status of a step."""
        self.cursor.execute("""
            UPDATE generation_steps SET validation_status = ?
            WHERE step_id = ?
        """, (status, step_id))
        self.conn.commit()

    def get_steps(self, session_id: int) -> List[dict]:
        """Retrieve all steps for a session."""
        self.cursor.execute("""
            SELECT * FROM generation_steps
            WHERE session_id = ?
            ORDER BY step_number
        """, (session_id,))
        return [dict(row) for row in self.cursor.fetchall()]

    def get_last_valid_state(self, session_id: int) -> List[dict]:
        """Retrieve all validated steps for backtracking."""
        self.cursor.execute("""
            SELECT code, reasoning FROM generation_steps
            WHERE session_id = ? AND validation_status = 'valid'
            ORDER BY step_number
        """, (session_id,))
        return [{"code": row["code"], "reasoning": row["reasoning"]}
                for row in self.cursor.fetchall()]

    # ── Validation Operations ────────────────────────────────────────────

    def log_validation(self, step_id: int, validator_type: str,
                       passed: bool, feedback: str,
                       confidence_score: float = None):
        """Log a validation result."""
        self.cursor.execute("""
            INSERT INTO validations (step_id, validator_type, passed, feedback, confidence_score)
            VALUES (?, ?, ?, ?, ?)
        """, (step_id, validator_type, passed, feedback, confidence_score))
        self.conn.commit()

    # ── Regeneration Operations ──────────────────────────────────────────

    def log_regeneration(self, original_step_id: int, attempt_number: int,
                         corrective_prompt: str, regenerated_code: str,
                         succeeded: bool = None):
        """Log a regeneration attempt."""
        self.cursor.execute("""
            INSERT INTO regenerations
            (original_step_id, attempt_number, corrective_prompt, regenerated_code, succeeded)
            VALUES (?, ?, ?, ?, ?)
        """, (original_step_id, attempt_number, corrective_prompt,
              regenerated_code, succeeded))
        self.conn.commit()

    # ── Evaluation Results ───────────────────────────────────────────────

    def save_evaluation_result(self, session_id: int, final_code: str,
                                tests_passed: int, tests_total: int,
                                total_tokens: int = 0,
                                total_corrections: int = 0,
                                execution_time: float = 0.0):
        """Save final evaluation results."""
        self.cursor.execute("""
            INSERT INTO evaluation_results
            (session_id, final_code, tests_passed, tests_total,
             total_tokens, total_corrections, execution_time_seconds)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (session_id, final_code, tests_passed, tests_total,
              total_tokens, total_corrections, execution_time))
        self.conn.commit()

    # ── Query Helpers ────────────────────────────────────────────────────

    def query(self, sql: str, params: tuple = ()) -> List[dict]:
        """Execute arbitrary SQL query and return results as dicts."""
        self.cursor.execute(sql, params)
        return [dict(row) for row in self.cursor.fetchall()]

    def close(self):
        """Close the database connection."""
        self.conn.close()
