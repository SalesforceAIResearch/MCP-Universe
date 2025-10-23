#!/usr/bin/env python3
"""
Enhanced Base Task Manager with Common Task Discovery Logic
===========================================================

This module provides an improved base class for task managers that consolidates
common task discovery patterns while maintaining flexibility for service-specific needs.
"""

import json
import subprocess
import sys
from abc import ABC
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

from src.logger import get_logger
from src.results_reporter import TaskResult

logger = get_logger(__name__)


@dataclass
class BaseTask:
    """Base class for evaluation tasks."""

    task_instruction_path: Path
    task_verification_path: Path
    service: str
    category_id: str  # From meta.json if available, otherwise directory name
    task_id: str  # From meta.json if available, otherwise directory name

    @property
    def name(self) -> str:
        """Return the task name using '__' separator format: 'category_id__task_id'."""
        return f"{self.category_id}__{self.task_id}"

    def get_task_instruction(self) -> str:
        """Return the full text content of the task instruction file."""
        if not self.task_instruction_path.exists():
            raise FileNotFoundError(
                f"Task instruction file not found: {self.task_instruction_path}"
            )

        return self.task_instruction_path.read_text(encoding="utf-8")


class BaseTaskManager(ABC):
    """Enhanced base class for service-specific task managers with common discovery logic."""

    def __init__(
        self,
        tasks_root: Path,
        mcp_service: str = None,
        task_class: type = None,
        task_organization: str = None,
    ):
        """Initialize the base task manager.

        Args:
            tasks_root: Root directory containing all tasks
            mcp_service: MCP service name (e.g., 'notion', 'github', 'filesystem')
            task_class: Custom task class to use (defaults to BaseTask)
            task_organization: 'file' or 'directory' based task organization
        """
        self.tasks_root = tasks_root
        self.mcp_service = mcp_service or self.__class__.__name__.lower().replace(
            "taskmanager", ""
        )
        self.task_class = task_class or BaseTask
        self.task_organization = task_organization
        self._tasks_cache = None

    # =========================================================================
    # Common Task Discovery Implementation
    # =========================================================================

    def discover_all_tasks(self) -> List[BaseTask]:
        """Discover all available tasks for this service (common implementation)."""
        if self._tasks_cache is not None:
            return self._tasks_cache

        tasks = []
        service_dir = self.tasks_root / (
            self.mcp_service or self._get_service_directory_name()
        )

        if not service_dir.exists():
            logger.warning(
                f"{self.mcp_service.title()} tasks directory does not exist: {service_dir}"
            )
            return tasks

        # Scan categories
        for category_dir in service_dir.iterdir():
            if not self._is_valid_category_dir(category_dir):
                continue

            category_id = category_dir.name
            logger.info("Discovering tasks in category: %s", category_id)

            # Find tasks using service-specific logic
            task_files = self._find_task_files(category_dir)
            for task_files_info in task_files:
                task = self._create_task_from_files(category_id, task_files_info)
                if task:
                    tasks.append(task)
                    logger.debug("Found task: %s", task.name)

        # Sort and cache
        # Sort by category_id and a stringified task_id to handle both numeric IDs and slugs uniformly
        self._tasks_cache = sorted(tasks, key=lambda t: (t.category_id, str(t.task_id)))
        logger.info(
            "Discovered %d %s tasks across all categories",
            len(self._tasks_cache),
            self.mcp_service.title(),
        )
        return self._tasks_cache

    def get_categories(self) -> List[str]:
        """Get a list of all task categories (common implementation)."""
        tasks = self.discover_all_tasks()
        return sorted(list(set(task.category_id for task in tasks)))

    def filter_tasks(self, task_filter: str) -> List[BaseTask]:
        """Filter tasks based on category or specific task pattern (common implementation)."""
        all_tasks = self.discover_all_tasks()

        if not task_filter or task_filter.lower() == "all":
            return all_tasks

        # Check if it's a category filter
        categories = self.get_categories()
        if task_filter in categories:
            return [task for task in all_tasks if task.category_id == task_filter]

        # Check for specific task pattern (category_id/task_id)
        if "/" in task_filter:
            try:
                category, task_part = task_filter.split("/", 1)

                # First try to match by task_id (could be numeric or string)
                for task in all_tasks:
                    if task.category_id == category:
                        # Check if task_id matches (as string or as specific pattern)
                        if str(task.task_id) == task_part:
                            return [task]
            except (ValueError, IndexError):
                pass

        # Fallback: check for partial matches in task names or categories
        filtered_tasks = []
        for task in all_tasks:
            if (
                task_filter in task.category_id
                or task_filter in task.name
                or task_filter == str(task.task_id)
            ):
                filtered_tasks.append(task)

        return filtered_tasks

    # =========================================================================
    # Common Helper Methods
    # =========================================================================

    def get_task_instruction(self, task: BaseTask) -> str:
        """Get formatted task instruction (template method)."""
        base_instruction = self._read_task_instruction(task)
        return self._format_task_instruction(base_instruction)

    def execute_task(self, task: BaseTask, agent_result: Dict[str, Any]) -> TaskResult:
        """Execute task verification (template method)."""
        logger.info(f"| Verifying task ({self.mcp_service.title()}): {task.name}")

        # Track agent success separately
        agent_success = agent_result.get("success", False)
        agent_error = None
        verification_success = False
        verification_error = None
        verification_output = None

        # Handle agent failure (but still continue to verification)
        if not agent_success:
            agent_error = agent_result.get("error", "Agent execution failed")
            # Standardize MCP network errors
            agent_error = self._standardize_error_message(agent_error)
            
            logger.error(f"| ✗ Agent execution failed for task")
            logger.error(f"| ⚠️ Error: {agent_error}")
            logger.info(f"| - Proceeding with verification despite agent failure")

        try:
            # Always run verification regardless of agent success
            verify_result = self.run_verification(task)

            # Process verification results
            verification_success = verify_result.returncode == 0
            verification_output = verify_result.stdout
            
            # Log verification output
            if verification_output:
                print(verification_output)
            
            # Capture verification error if failed
            if not verification_success:
                verification_error = verify_result.stderr if verify_result.stderr else "Verification failed with no error message"

            if verification_success:
                logger.info(f"| Verification Result: \033[92m✓ PASSED\033[0m")
            else:
                logger.error(f"| Verification Result: \033[91m✗ FAILED\033[0m")
                if verification_error:
                    logger.error(f"| Verification Error: {verification_error}")

            return TaskResult(
                task_name=task.name,
                success=verification_success,
                error_message=agent_error,  # Agent execution error
                verification_error=verification_error,  # Verification error
                verification_output=verification_output,  # Verification output
                model_output=agent_result.get("output", ""),
                category_id=task.category_id,
                task_id=task.task_id,
                token_usage=agent_result.get("token_usage", {}),
                turn_count=agent_result.get("turn_count", -1),
            )

        except Exception as e:
            logger.error(f"| Task verification failed: {e}", exc_info=True)
            return TaskResult(
                task_name=task.name,
                success=False,
                error_message=agent_error,  # Keep agent error if any
                verification_error=str(e),  # Verification exception
                verification_output=None,
                category_id=task.category_id,
                task_id=task.task_id,
                model_output=agent_result.get("output", ""),
                token_usage=agent_result.get("token_usage", {}),
                turn_count=agent_result.get("turn_count", 0),
            )

    def run_verification(self, task: BaseTask) -> subprocess.CompletedProcess:
        """Run the verification script for a task (can be overridden).

        Default implementation runs the verification command.
        Services can override this to add environment variables or custom logic.
        """
        return subprocess.run(
            self._get_verification_command(task),
            capture_output=True,  # Capture stdout and stderr for logging
            text=True,
            timeout=300,
        )

    # =========================================================================
    # Abstract Methods - Minimal Set Required
    # =========================================================================

    def _get_service_directory_name(self) -> str:
        """Return the service directory name (e.g., 'notion', 'github').

        Default implementation uses the service parameter if provided.
        """
        if self.mcp_service:
            return self.mcp_service
        raise NotImplementedError(
            "Must provide service parameter or implement _get_service_directory_name"
        )

    def _get_task_organization(self) -> str:
        """Return task organization type: 'directory' or 'file'.

        - 'directory': Tasks organized as task_X/description.md (Notion)
        - 'file': Tasks organized as task_X.md (GitHub, Filesystem)

        Default implementation uses the task_organization parameter if provided.
        """
        if self.task_organization:
            return self.task_organization
        raise NotImplementedError(
            "Must provide task_organization parameter or implement _get_task_organization"
        )

    # Note: _create_task_instance is no longer needed - use task_class parameter instead

    # =========================================================================
    # Hook Methods with Smart Defaults
    # =========================================================================

    def _is_valid_category_dir(self, category_dir: Path) -> bool:
        """Check if a directory is a valid category directory."""
        return (
            category_dir.is_dir()
            and not category_dir.name.startswith(".")
            and category_dir.name != "utils"
            and category_dir.name != "__pycache__"
        )

    def _find_task_files(self, category_dir: Path) -> List[Dict[str, Any]]:
        """Find task files in a category directory (smart default implementation).

        Automatically handles both directory-based and file-based organization.
        """
        task_files: List[Dict[str, Any]] = []

        for task_dir in category_dir.iterdir():
            # Skip anything that is not a directory or is hidden
            if not task_dir.is_dir() or task_dir.name.startswith("."):
                continue

            description_path = task_dir / "description.md"
            verify_path = task_dir / "verify.py"

            # We consider a directory a valid task only if the two mandatory files exist
            if not (description_path.exists() and verify_path.exists()):
                logger.warning(
                    "Skipping %s – missing description.md or verify.py", task_dir
                )
                continue

            task_files.append(
                {
                    "task_id": task_dir.name,
                    "instruction_path": description_path,
                    "verification_path": verify_path,
                }
            )

        return task_files

    def _create_task_from_files(
        self, category_id: str, task_files_info: Dict[str, Any]
    ) -> Optional[BaseTask]:
        """Create a task from file information with meta.json support."""
        # Check for meta.json
        meta_path = task_files_info["instruction_path"].parent / "meta.json"
        # Default to directory names
        task_id = task_files_info["task_id"]
        final_category_id = category_id
        
        if meta_path.exists():
            try:
                with open(meta_path, 'r') as f:
                    meta_data = json.load(f)
                    # Use values from meta.json if available
                    final_category_id = meta_data.get("category_id", category_id)
                    task_id = meta_data.get("task_id", task_id)
            except Exception as e:
                logger.warning(f"Failed to load meta.json from {meta_path}: {e}")
        
        return self.task_class(
            task_instruction_path=task_files_info["instruction_path"],
            task_verification_path=task_files_info["verification_path"],
            service=self.mcp_service,
            category_id=final_category_id,
            task_id=task_id,
        )

    def _read_task_instruction(self, task: BaseTask) -> str:
        """Read and return the task instruction content."""
        return task.get_task_instruction()

    def _format_task_instruction(self, base_instruction: str) -> str:
        """Format task instruction with Notion-specific additions."""
        return (
            base_instruction
            + "\n\nNote: Based on your understanding, solve the task all at once by yourself, don't ask for my opinions on anything."
        )

    def _get_verification_command(self, task: BaseTask) -> List[str]:
        """Get the command to run task verification (default implementation)."""
        return [sys.executable, str(task.task_verification_path)]

    def _standardize_error_message(self, error_message: str) -> str:
        """Standardize error messages for consistent reporting."""
        from src.errors import standardize_error_message

        return standardize_error_message(error_message, mcp_service=self.mcp_service)
