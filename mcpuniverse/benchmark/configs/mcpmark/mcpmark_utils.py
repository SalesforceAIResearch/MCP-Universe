"""
MCPMark State Manager Integration Utilities
==========================================

This module provides integration functions for MCPMark state managers
to work with MCPUniverse's prepare/cleanup system.
"""

import sys
import logging
from pathlib import Path
import time

from mcpuniverse.common.context import Context
from mcpuniverse.benchmark.prepares import prepare_func
from mcpuniverse.benchmark.cleanups import cleanup_func

logger = logging.getLogger(__name__)


def _add_mcpmark_to_path():
    """Add mcpmark dependencies directory to Python path for imports."""
    # Get project root directory (parent of mcpuniverse package)
    project_root = Path(__file__).parent.parent.parent.parent.parent
    # Add project root to path so third_party module can be found
    if str(project_root) not in sys.path:
        sys.path.insert(0, str(project_root))
    # Also add third_party/mcpmark for direct imports
    mcpmark_deps_path = project_root / "third_party" / "mcpmark"
    if str(mcpmark_deps_path) not in sys.path:
        sys.path.insert(0, str(mcpmark_deps_path))
    return mcpmark_deps_path


# =============================================================================
# GitHub State Manager Integration
# =============================================================================

@prepare_func("mcpmark_github_setup")
async def mcpmark_github_setup(context: Context = None, category: str = None, **_kwargs):
    """
    Setup GitHub environment for MCPMark tasks.
    
    This function mimics the GitHubStateManager.set_up() behavior:
    - Creates/imports GitHub repositories for task isolation
    - Sets up evaluation workspace
    
    Args:
        context: Execution context (automatically passed by mcpuniverse)
        category: Task category (automatically passed by mcpuniverse)
        **kwargs: Additional arguments from prepare_args
    """
    try:
        # Add mcpmark to path
        _add_mcpmark_to_path()

        # Import mcpmark modules
        from src.mcp_services.github.github_state_manager import GitHubStateManager  # pylint: disable=import-error, import-outside-toplevel
        # from src.base.task_manager import BaseTask

        # Get GitHub token from context
        if not context:
            raise ValueError("Context required for GitHub setup")

        github_token = context.get_env("GITHUB_TOKENS")
        if not github_token:
            raise ValueError("GITHUB_TOKENS required")

        # Create a mock task object with proper attributes
        class MockTask:
            """Lightweight task placeholder for GitHubStateManager interaction."""
            # pylint: disable=too-few-public-methods
            def __init__(self, category_id, task_id=None):
                self.category_id = category_id
                self.task_id = task_id or f"mcpuniverse_task_{category_id}"
                self.name = f"{category_id}__{self.task_id}"
                # Add other attributes that might be needed
                self.repository_url = None  # Will be set by state manager

        # Generate a unique task ID based on category and timestamp
        task_id = f"task_{int(time.time())}"
        mock_task = MockTask(category or "build_your_own_x", task_id)

        logger.info("Setting up GitHub environment for task: %s", mock_task.name)

        # Initialize state manager
        state_manager = GitHubStateManager(
            github_token=github_token,
            eval_org=context.get_env("GITHUB_EVAL_ORG", "mcpmark-eval")
        )

        # Call setup
        success = state_manager.set_up(mock_task)

        if success:
            # Store state manager in context for cleanup
            if context:
                context.env["MCPMARK_GITHUB_STATE_MANAGER"] = state_manager
                context.env["MCPMARK_GITHUB_TASK"] = mock_task
                # Store the repository URL for potential use by evaluators
                if hasattr(mock_task, 'repository_url') and mock_task.repository_url:
                    context.env["MCPMARK_GITHUB_REPO_URL"] = mock_task.repository_url

            logger.info("GitHub environment setup completed for task: %s", mock_task.name)
            return f"GitHub environment setup completed for task: {mock_task.name}"

        raise RuntimeError("GitHub setup failed")

    except Exception as e:
        logger.error("Failed to setup GitHub environment: %s", e, exc_info=True)
        raise


@cleanup_func("mcpmark", "github_cleanup")
async def mcpmark_github_cleanup(context: Context = None, **_kwargs):
    """
    Cleanup GitHub environment for MCPMark tasks.
    
    This function mimics the GitHubStateManager.clean_up() behavior:
    - Deletes created repositories
    - Cleans up evaluation workspace
    """
    try:
        if not context:
            logger.warning("No context provided for GitHub cleanup")
            return "No context for cleanup"

        # Get state manager from context
        state_manager = context.env.get("MCPMARK_GITHUB_STATE_MANAGER")
        task = context.env.get("MCPMARK_GITHUB_TASK")

        if not state_manager:
            logger.warning("No GitHub state manager found in context")
            return "No state manager to cleanup"

        # Call cleanup
        success = state_manager.clean_up(task)

        # Clear from context
        context.env.pop("MCPMARK_GITHUB_STATE_MANAGER", None)
        context.env.pop("MCPMARK_GITHUB_TASK", None)

        if success:
            logger.info("GitHub environment cleanup completed")
            return "GitHub environment cleanup completed"

        logger.warning("GitHub cleanup completed with some failures")
        return "GitHub cleanup completed with warnings"

    except Exception as e:  # pylint: disable=broad-exception-caught
        logger.error("Failed to cleanup GitHub environment: %s", e, exc_info=True)
        return f"GitHub cleanup failed: {e}"
