import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from src.logger import get_logger
from .task_manager import BaseTask

# Initialize logger
logger = get_logger(__name__)


@dataclass
class InitialStateInfo:
    """Information about created initial state for a task."""

    state_id: str
    state_url: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None


class BaseStateManager(ABC):
    """
    Simplified abstract base class for state management in MCP services.

    This class provides essential functionality for initial state creation and cleanup
    while allowing service-specific implementations through template methods.
    """

    def __init__(self, service_name: str):
        self.service_name = service_name
        # Simple resource tracking for cleanup
        self.tracked_resources: List[Dict[str, Any]] = []

    # Note: Initialization is now handled in service-specific constructors

    def set_up(self, task: BaseTask) -> bool:
        """Set up initial state for a specific task.

        Args:
            task: The task for which to set up the initial state

        Returns:
            True if setup successful, False otherwise
        """
        try:
            logger.info(
                f"| Setting up initial state for {self.service_name} task: {task.name}"
            )

            # Create initial state
            initial_state_info = self._create_initial_state(task)
            if not initial_state_info:
                logger.error(f"| Failed to create initial state for {task.name}")
                return False

            # Store initial state info in task
            self._store_initial_state_info(task, initial_state_info)

            logger.info(f"| ✓ Initial state setup completed for {task.name}")
            return True

        except Exception as e:
            logger.error(f"| Setup failed for {task.name}: {e}")
            return False

    def clean_up(self, task: BaseTask = None) -> bool:
        """Clean up resources with common patterns and service-specific hooks.

        Args:
            task: Optional task to clean up specific resources for

        Returns:
            True if cleanup successful, False otherwise
        """
        try:
            cleanup_success = True

            # Task-specific cleanup
            if task:
                logger.info(
                    f"| ○ Cleaning up initial state for {self.service_name} task: {task.name}"
                )
                if not self._cleanup_task_initial_state(task):
                    cleanup_success = False

            # Clean up all tracked resources
            if not self._cleanup_tracked_resources():
                cleanup_success = False

            if cleanup_success:
                logger.info(f"| ✓ Cleanup completed for {self.service_name}")
            else:
                logger.warning(
                    f"| Cleanup completed with some failures for {self.service_name}"
                )

            return cleanup_success

        except Exception as e:
            logger.error(f"Cleanup failed for {self.service_name}: {e}")
            return False

    def track_resource(
        self,
        resource_type: str,
        identifier: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Track a resource for later cleanup.

        Args:
            resource_type: Type of resource (e.g., 'repository', 'page')
            identifier: Unique identifier for the resource
            metadata: Additional metadata about the resource
        """
        resource = {
            "type": resource_type,
            "id": identifier,
            "created_at": time.time(),
            "metadata": metadata or {},
        }
        self.tracked_resources.append(resource)
        logger.debug(f"Tracked {resource_type} resource: {identifier}")

    def get_service_config_for_agent(self) -> dict:
        """
        Get service-specific configuration for agent execution.

        This method should be overridden by service implementations that need
        to provide additional configuration to the agent.

        Returns:
            Dictionary containing configuration needed by the agent/MCP server
        """
        return {}

    def set_verification_environment(self, messages_path: str = None) -> None:
        """
        Set environment variables needed for verification scripts.

        Args:
            messages_path: Optional path to messages.json file for verification

        This method can be overridden by service implementations that need
        to set specific environment variables for their verification scripts.
        The default implementation sets MCP_MESSAGES if provided.
        """
        import os
        if messages_path:
            os.environ["MCP_MESSAGES"] = str(messages_path)

    def _cleanup_tracked_resources(self) -> bool:
        """Clean up all tracked resources."""
        cleanup_success = True

        for resource in self.tracked_resources:
            try:
                if not self._cleanup_single_resource(resource):
                    cleanup_success = False
            except Exception as e:
                logger.error(f"Failed to cleanup resource {resource}: {e}")
                cleanup_success = False

        # Clear resources after cleanup attempt
        self.tracked_resources.clear()
        return cleanup_success

    # =========================================================================
    # Abstract methods for service-specific behavior (simplified)
    # =========================================================================

    # Note: Service-specific initialization is now handled in constructors

    @abstractmethod
    def _create_initial_state(self, task: BaseTask) -> Optional[InitialStateInfo]:
        """Create initial state for a task (e.g., duplicate page, fork repo).

        Args:
            task: Task for which to create initial state

        Returns:
            InitialStateInfo object or None if creation failed
        """
        pass

    @abstractmethod
    def _store_initial_state_info(
        self, task: BaseTask, state_info: InitialStateInfo
    ) -> None:
        """Store initial state information in the task object.

        Args:
            task: Task object to update
            state_info: Initial state information to store
        """
        pass

    @abstractmethod
    def _cleanup_task_initial_state(self, task: BaseTask) -> bool:
        """Clean up initial state for a specific task.

        Args:
            task: Task whose initial state should be cleaned up

        Returns:
            True if cleanup successful, False otherwise
        """
        pass

    @abstractmethod
    def _cleanup_single_resource(self, resource: Dict[str, Any]) -> bool:
        """Clean up a single tracked resource.

        Args:
            resource: Resource dictionary with type, id, and metadata

        Returns:
            True if cleanup successful, False otherwise
        """
        pass
