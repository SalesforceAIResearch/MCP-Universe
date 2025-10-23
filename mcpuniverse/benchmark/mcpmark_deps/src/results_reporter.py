#!/usr/bin/env python3
"""
Results Reporter for MCPMark Evaluation Pipeline
================================================

This module provides utilities for saving evaluation results in a structured format.
"""

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from src.logger import get_logger

# Initialize logger
logger = get_logger(__name__)


@dataclass
class TaskResult:
    """
    Represents the result of a single task evaluation.

    Attributes:
        task_name: The full name of the task (e.g., "category_id__task_id").
        success: Whether the task completed successfully.
        category_id: The task category ID.
        task_id: The task identifier (number or slug).
        error_message: Error message from agent execution if it failed.
        verification_error: Error message from verification if it failed.
        verification_output: Captured stdout from verification script.
        model_output: Agent conversation trajectory (messages).
        token_usage: Token usage statistics.
        turn_count: Number of turns taken during task execution.
        agent_execution_time: Time for Step 2 (agent execution) in seconds.
        task_execution_time: Total time for Steps 1-4 in seconds.
    """

    task_name: str
    success: bool
    category_id: Optional[str] = None
    task_id: Optional[str] = None
    error_message: Optional[str] = None  # Agent execution error
    verification_error: Optional[str] = None  # Verification error (separate from agent error)
    verification_output: Optional[str] = None  # Verification stdout/stderr
    model_output: Optional[Any] = None  # Agent conversation trajectory
    token_usage: Optional[Dict[str, int]] = None  # Token usage statistics
    turn_count: Optional[int] = None  # Number of turns taken during task execution
    agent_execution_time: float = 0.0  # Time for Step 2 (agent execution) in seconds
    task_execution_time: float = 0.0  # Total time for Steps 1-4 in seconds

    @property
    def status(self) -> str:
        """Returns the status of the task as 'PASS' or 'FAIL'."""
        return "PASS" if self.success else "FAIL"


@dataclass
class EvaluationReport:
    """Represents a complete evaluation report for a model."""

    model_name: str
    model_config: Dict[str, Any]
    total_tasks: int
    successful_tasks: int
    failed_tasks: int
    task_results: List[TaskResult]
    tasks_filter: Optional[str] = None

    @property
    def success_rate(self) -> float:
        """Calculates the overall success rate as a percentage."""
        if self.total_tasks == 0:
            return 0.0
        return (self.successful_tasks / self.total_tasks) * 100

    @property
    def total_input_tokens(self) -> int:
        """Calculate total input tokens across all tasks."""
        total = 0
        for result in self.task_results:
            if result.token_usage:
                total += (result.token_usage.get("input_tokens") or 0)
        return total

    @property
    def total_output_tokens(self) -> int:
        """Calculate total output tokens across all tasks."""
        total = 0
        for result in self.task_results:
            if result.token_usage:
                total += (result.token_usage.get("output_tokens") or 0)
        return total

    @property
    def total_tokens(self) -> int:
        """Calculate total tokens across all tasks."""
        total = 0
        for result in self.task_results:
            if result.token_usage:
                total += (result.token_usage.get("total_tokens") or 0)
        return total
    
    @property
    def total_reasoning_tokens(self) -> int:
        """Calculate total reasoning tokens across all tasks."""
        total = 0
        for result in self.task_results:
            if result.token_usage:
                total += (result.token_usage.get("reasoning_tokens") or 0)
        return total

    @property
    def avg_input_tokens(self) -> float:
        """Calculate average input tokens per task."""
        if self.total_tasks == 0:
            return 0.0
        return self.total_input_tokens / self.total_tasks

    @property
    def avg_output_tokens(self) -> float:
        """Calculate average output tokens per task."""
        if self.total_tasks == 0:
            return 0.0
        return self.total_output_tokens / self.total_tasks

    @property
    def avg_total_tokens(self) -> float:
        """Calculate average total tokens per task."""
        if self.total_tasks == 0:
            return 0.0
        return self.total_tokens / self.total_tasks
    
    @property
    def avg_reasoning_tokens(self) -> float:
        """Calculate average reasoning tokens per task."""
        if self.total_tasks == 0:
            return 0.0
        return self.total_reasoning_tokens / self.total_tasks

    @property
    def total_task_execution_time(self) -> float:
        """Calculates the total task execution time from sum of all task execution times."""
        # Use sum of individual task execution times instead of pipeline wall clock time
        # This ensures resume functionality shows correct total time
        return sum(task.task_execution_time for task in self.task_results)
    
    @property
    def total_agent_execution_time(self) -> float:
        """Calculates the total agent execution time (Step 2) across all tasks."""
        return sum(task.agent_execution_time for task in self.task_results)

    def get_category_stats(self) -> Dict[str, Dict[str, Any]]:
        """
        Calculates and returns success statistics grouped by task category.
        """
        category_stats = {}

        for result in self.task_results:
            category = result.category_id or "Uncategorized"
            if category not in category_stats:
                category_stats[category] = {
                    "total": 0,
                    "successful": 0,
                    "failed": 0,
                    "success_rate": 0.0,
                    "avg_execution_time": 0.0,
                    "avg_agent_execution_time": 0.0,
                    "total_input_tokens": 0,
                    "total_output_tokens": 0,
                    "total_tokens": 0,
                    "total_reasoning_tokens": 0,
                    "avg_input_tokens": 0.0,
                    "avg_output_tokens": 0.0,
                    "avg_total_tokens": 0.0,
                    "avg_reasoning_tokens": 0.0,
                    "total_turns": 0,
                    "avg_turns": 0.0,
                }

            category_stats[category]["total"] += 1
            if result.success:
                category_stats[category]["successful"] += 1
            else:
                category_stats[category]["failed"] += 1

            # Add token and turn usage
            if result.token_usage:
                category_stats[category]["total_input_tokens"] += (
                    result.token_usage.get("input_tokens") or 0
                )
                category_stats[category]["total_output_tokens"] += (
                    result.token_usage.get("output_tokens") or 0
                )
                category_stats[category]["total_tokens"] += (
                    result.token_usage.get("total_tokens") or 0
                )
                category_stats[category]["total_reasoning_tokens"] += result.token_usage.get(
                    "reasoning_tokens", 0
                ) or 0

            # Accumulate turns
            if result.turn_count is not None:
                category_stats[category]["total_turns"] += result.turn_count

        # Calculate derived metrics like success rate and average time
        for category, stats in category_stats.items():
            if stats["total"] > 0:
                stats["success_rate"] = (stats["successful"] / stats["total"]) * 100
                category_results = [
                    r
                    for r in self.task_results
                    if (r.category_id or "Uncategorized") == category
                ]
                total_time = sum(r.task_execution_time for r in category_results)
                stats["avg_execution_time"] = total_time / len(category_results)
                
                # Add agent execution time stats
                total_agent_time = sum(r.agent_execution_time for r in category_results)
                stats["avg_agent_execution_time"] = total_agent_time / len(category_results)

                # Calculate average tokens and turns
                stats["avg_input_tokens"] = stats["total_input_tokens"] / stats["total"]
                stats["avg_output_tokens"] = (
                    stats["total_output_tokens"] / stats["total"]
                )
                stats["avg_total_tokens"] = stats["total_tokens"] / stats["total"]
                stats["avg_reasoning_tokens"] = stats["total_reasoning_tokens"] / stats["total"]

                stats["avg_turns"] = (
                    stats["total_turns"] / stats["total"] if stats["total"] > 0 else 0
                )

        return category_stats


class ResultsReporter:
    """Handles saving evaluation results in structured formats."""

    def __init__(self):
        """Initialize the results reporter."""
        pass

    def save_messages_json(self, messages: Any, output_path: Path) -> Path:
        """Saves the conversation messages/trajectory as messages.json."""
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with output_path.open("w", encoding="utf-8") as f:
            json.dump(messages, f, indent=2, ensure_ascii=False)
        return output_path

    def save_meta_json(
        self,
        task_result: TaskResult,
        model_config: Dict[str, Any],
        start_time: datetime,
        end_time: datetime,
        output_path: Path,
    ) -> Path:
        """Saves task metadata (excluding messages) as meta.json."""
        output_path.parent.mkdir(parents=True, exist_ok=True)

        meta_data = {
            "task_name": task_result.task_name,
            "model_name": model_config.get("model_name", "unknown"),
            "litellm_run_model_name": model_config.get("litellm_run_model_name"),
            "reasoning_effort": model_config.get("reasoning_effort"),
            "mcp": model_config.get("mcp_service", "unknown"),
            "timeout": model_config.get("timeout", 300),
            "time": {"start": start_time.isoformat(), "end": end_time.isoformat()},
            "agent_execution_time": task_result.agent_execution_time,
            "task_execution_time": task_result.task_execution_time,
            "execution_result": {
                "success": task_result.success,
                "error_message": task_result.error_message,
                "verification_error": task_result.verification_error,
                "verification_output": task_result.verification_output,
            },
            "token_usage": task_result.token_usage or {},
            "turn_count": task_result.turn_count,
        }

        with output_path.open("w", encoding="utf-8") as f:
            json.dump(meta_data, f, indent=2, ensure_ascii=False)
        return output_path

    def save_model_summary(self, report: EvaluationReport, output_path: Path) -> Path:
        """Saves a concise model-level summary."""
        output_path.parent.mkdir(parents=True, exist_ok=True)

        category_stats = report.get_category_stats()

        # Aggregate turn counts using category_stats
        total_turns = sum(stats["total_turns"] for stats in category_stats.values())
        avg_turns = total_turns / report.total_tasks if report.total_tasks > 0 else 0

        summary = {
            "model_name": report.model_name,
            "model_config": report.model_config,
            "total_tasks": report.total_tasks,
            "successful_tasks": report.successful_tasks,
            "failed_tasks": report.failed_tasks,
            "success_rate": round(report.success_rate, 2),
            "total_task_execution_time": report.total_task_execution_time,
            "average_task_execution_time": report.total_task_execution_time / report.total_tasks
            if report.total_tasks > 0
            else 0,
            "total_agent_execution_time": report.total_agent_execution_time,
            "average_agent_execution_time": report.total_agent_execution_time / report.total_tasks
            if report.total_tasks > 0
            else 0,
            "token_usage": {
                "total_input_tokens": report.total_input_tokens,
                "total_output_tokens": report.total_output_tokens,
                "total_tokens": report.total_tokens,
                "total_reasoning_tokens": report.total_reasoning_tokens,
                "avg_input_tokens": round(report.avg_input_tokens, 2),
                "avg_output_tokens": round(report.avg_output_tokens, 2),
                "avg_total_tokens": round(report.avg_total_tokens, 2),
                "avg_reasoning_tokens": round(report.avg_reasoning_tokens, 2),
            },
            "turn_usage": {
                "total_turns": total_turns,
                "avg_turns": round(avg_turns, 2),
            },
            "category_breakdown": {
                category: {
                    "total": stats["total"],
                    "success_rate": round(stats["success_rate"], 2),
                    "avg_time": round(stats["avg_execution_time"], 2),
                    "token_usage": {
                        "total_input": stats["total_input_tokens"],
                        "total_output": stats["total_output_tokens"],
                        "total": stats["total_tokens"],
                        "total_reasoning": stats["total_reasoning_tokens"],
                        "avg_input": round(stats["avg_input_tokens"], 2),
                        "avg_output": round(stats["avg_output_tokens"], 2),
                        "avg_total": round(stats["avg_total_tokens"], 2),
                        "avg_reasoning": round(stats["avg_reasoning_tokens"], 2),
                    },
                    "turn_usage": {
                        "total_turns": stats["total_turns"],
                        "avg_turns": round(stats["avg_turns"], 2),
                    },
                }
                for category, stats in category_stats.items()
            },
        }

        with output_path.open("w", encoding="utf-8") as f:
            json.dump(summary, f, indent=2, ensure_ascii=False)
        return output_path
