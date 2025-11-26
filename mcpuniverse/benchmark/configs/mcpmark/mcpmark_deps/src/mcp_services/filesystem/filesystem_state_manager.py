"""
Filesystem State Manager for MCPMark
=====================================

This module handles filesystem state management for consistent task evaluation.
It manages test directories, file creation/cleanup, and environment isolation.
"""
# pylint: disable=import-error
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional

from src.base.state_manager import BaseStateManager
from src.base.task_manager import BaseTask
from src.logger import get_logger

logger = get_logger(__name__)


class FilesystemStateManager(BaseStateManager):
    """
    Manages filesystem state for task evaluation.

    This includes creating isolated test directories, tracking created resources,
    and cleaning up after task completion.
    """

    def _get_project_root(self) -> Path:
        """Find project root by looking for marker files."""
        current = Path(__file__).resolve()

        # Look for project root markers
        for parent in current.parents:
            if (parent / "pyproject.toml").exists() or (parent / "pipeline.py").exists():
                return parent

        # Fallback to old method if markers not found
        return Path(__file__).parent / "../../../"

    def __init__(self, test_root: Optional[Path] = None, cleanup_on_exit: bool = False):
        """
        Initialize filesystem state manager.

        Args:
            test_root: Root directory for test operations
                (from FILESYSTEM_TEST_ROOT env var)
            cleanup_on_exit: Whether to clean up test directories after tasks
                (default False for persistent environment)
        """
        super().__init__(service_name="filesystem")

        # Use provided test root or default to persistent test environment
        if test_root:
            self.test_root = Path(test_root)
        else:
            # Default to persistent test environment
            project_root = self._get_project_root()
            self.test_root = (project_root / "test_environments/desktop").resolve()

        self.cleanup_on_exit = cleanup_on_exit
        self.current_task_dir: Optional[Path] = None
        self.created_resources: List[Path] = []

        # Backup and restore functionality
        self.backup_dir: Optional[Path] = None
        self.backup_enabled = (
            True  # Enable backup/restore by default for task isolation
        )
        # Current task category for URL selection
        self._current_task_category: Optional[str] = None

        logger.info(
            "Initialized FilesystemStateManager with persistent test environment: %s",
            self.test_root
        )

    def initialize(self, **_kwargs) -> bool:  # pylint: disable=unused-argument
        """
        Initialize the filesystem environment.

        Ensures the persistent test environment exists and is accessible.

        Returns:
            bool: True if initialization successful
        """
        try:
            # Ensure test environment directory exists
            if not self.test_root.exists():
                logger.error(
                    "Persistent test environment not found: %s",
                    self.test_root
                )
                logger.error(
                    "Please ensure test_environments/desktop/ exists in the repository"
                )
                return False

            logger.info("Using persistent test environment: %s", self.test_root)

            # Verify we can write to the directory
            test_file = self.test_root / ".mcpbench_test"
            test_file.write_text("test")
            test_file.unlink()

            return True

        except Exception as exc:  # pylint: disable=broad-exception-caught
            logger.error("Failed to initialize filesystem environment: %s", exc)
            return False

    def set_up(self, task: BaseTask) -> bool:
        """
        Set up filesystem environment for a specific task.

        Creates a backup of the current environment, then uses the backup
        as the working directory to keep the original unchanged.

        Args:
            task: The task for which to set up the state

        Returns:
            bool: True if setup successful
        """
        try:
            # Dynamically set test root based on task category
            self._set_dynamic_test_root(task)

            # Create backup of current test environment before task execution
            if self.backup_enabled:
                if not self._create_backup(task):
                    logger.error("Failed to create backup for task %s", task.name)
                    return False

            # Use the backup directory as the working directory instead of the original
            self.current_task_dir = (
                self.backup_dir
            )  # Use backup directory for operations

            logger.info("| ✓ Using the backup environment for operations")

            # Store the test directory path in the task object for use by task manager
            if hasattr(task, "__dict__"):
                task.test_directory = str(self.current_task_dir)

            # Set environment variable for verification scripts and MCP server
            os.environ["FILESYSTEM_TEST_DIR"] = str(self.current_task_dir)

            return True

        except Exception as exc:  # pylint: disable=broad-exception-caught
            logger.error(
                "Failed to set up filesystem state for %s: %s",
                task.name,
                exc
            )
            return False

    def _set_dynamic_test_root(self, task: BaseTask) -> None:
        """
        Dynamically set the test root directory based on the task category.

        Args:
            task: The task for which to set the test root
        """
        # Get the base test environments directory from environment variable
        base_test_root = os.getenv("FILESYSTEM_TEST_ROOT")
        if not base_test_root:
            # Fallback to default path
            project_root = self._get_project_root()
            base_test_root = str(project_root / "test_environments")

        base_test_path = Path(base_test_root)

        # If task has a category_id, append it to the base path
        if task.category_id:
            self.test_root = base_test_path / task.category_id
            # Store the current task category for URL selection
            self._current_task_category = task.category_id  # pylint: disable=attribute-defined-outside-init
            logger.info(
                "| ✓ Setting test root to category-specific directory: %s",
                self.test_root
            )
        else:
            # Use the base test environments directory
            self.test_root = base_test_path
            # For base directory, use 'desktop' as default category
            self._current_task_category = 'desktop'
            logger.info(
                "| Setting test root to base directory: %s",
                self.test_root
            )

        # Ensure the directory exists by downloading and extracting if needed
        if not self.test_root.exists():
            logger.warning("| Test directory does not exist: %s", self.test_root)
            if not self._download_and_extract_test_environment():
                logger.error(
                    "Failed to download and extract test environment for: %s",
                    self.test_root
                )
                raise RuntimeError(
                    f"Test environment not available: {self.test_root}"
                )
            logger.info(
                "| Downloaded and extracted test environment: %s",
                self.test_root
            )


    def clean_up(self, task: Optional[BaseTask] = None, **_kwargs) -> bool:  # pylint: disable=unused-argument
        """
        Clean up filesystem resources created during task execution.

        Since we operate on the backup directory, we just need to clean up the backup.

        Args:
            task: The task to clean up after (optional)
            **kwargs: Additional cleanup options

        Returns:
            bool: True if cleanup successful
        """
        try:
            cleanup_success = True

            # Clean up the backup directory since we operated on it
            if self.backup_enabled and self.backup_dir and self.backup_dir.exists():
                try:
                    shutil.rmtree(self.backup_dir)
                    task_name = task.name if task else 'unknown'
                    logger.info(
                        "| ✓ Cleaned up backup directory for task %s",
                        task_name
                    )
                    self.backup_dir = None
                except Exception as exc:  # pylint: disable=broad-exception-caught
                    logger.error("Failed to clean up backup directory: %s", exc)
                    cleanup_success = False
            else:
                logger.info("No backup directory to clean up")

            # Clear the resources list
            self.created_resources.clear()

            return cleanup_success

        except Exception as exc:  # pylint: disable=broad-exception-caught
            logger.error("Filesystem cleanup failed: %s", exc)
            return False

    def get_test_directory(self) -> Optional[Path]:
        """
        Get the current test directory path.

        Returns:
            Path to the current test directory, or None if not set up
        """
        return self.current_task_dir

    def get_service_config_for_agent(self) -> dict:
        """
        Get service-specific configuration for agent execution.

        Returns:
            Dictionary containing configuration needed by the agent/MCP server
        """
        service_config = {}

        # Add test directory if available
        if self.current_task_dir:
            service_config["test_directory"] = str(self.current_task_dir)

        return service_config

    def track_resource(self, resource_path: Path):
        """
        Track a resource for cleanup.

        Args:
            resource_path: Path to the resource to track
        """
        if resource_path not in self.created_resources:
            self.created_resources.append(resource_path)
            logger.debug(f"Tracking resource for cleanup: {resource_path}")

    def reset_test_environment(self) -> bool:
        """
        Reset the test environment to its original state.

        This method can be used for development/debugging purposes.
        In normal operation, the persistent environment is maintained.

        Returns:
            bool: True if reset successful
        """
        try:
            # Remove any sorting directories that might have been created
            sorting_dirs = ["has_test", "no_test", "organized", "backup"]
            for dir_name in sorting_dirs:
                dir_path = self.test_root / dir_name
                if dir_path.exists():
                    shutil.rmtree(dir_path)
                    logger.info("Removed sorting directory: %s", dir_path)

            # Remove any temporary files that might have been created
            temp_files = ["hello_world.txt", "new_file.txt", "temp.txt"]
            for file_name in temp_files:
                file_path = self.test_root / file_name
                if file_path.exists():
                    file_path.unlink()
                    logger.info("Removed temporary file: %s", file_path)

            logger.info("Test environment reset completed")
            return True
        except Exception as exc:  # pylint: disable=broad-exception-caught
            logger.error("Test environment reset failed: %s", exc)
            return False

    # =========================================================================
    # Backup and Restore Methods for Task Isolation
    # =========================================================================

    def _create_backup(self, task: BaseTask) -> bool:
        """
        Create a complete backup of the test environment before task execution.

        Args:
            task: The task for which to create backup

        Returns:
            bool: True if backup successful
        """
        try:
            # Use FILESYSTEM_TEST_DIR directly as the backup directory
            # This allows MCP server to use a fixed path without dynamic updates
            backup_dir_env = os.getenv("FILESYSTEM_TEST_DIR")

            if backup_dir_env:
                # Use the environment variable path with category subdirectory
                backup_base = Path(backup_dir_env).resolve()
                self.backup_dir = backup_base / task.category_id
                logger.info(
                    "| Using FILESYSTEM_TEST_DIR as backup directory: %s",
                    self.backup_dir
                )
            else:
                # Fallback to original behavior
                project_root = self._get_project_root()
                backup_root = (project_root / ".mcpmark_backups").resolve()
                backup_root.mkdir(exist_ok=True)
                self.backup_dir = backup_root / f"{task.category_id}"
                logger.info(
                    "| Using default backup directory: %s",
                    self.backup_dir
                )

            # Ensure parent directory exists
            self.backup_dir.parent.mkdir(parents=True, exist_ok=True)

            # Remove existing backup if it exists
            if self.backup_dir.exists():
                shutil.rmtree(self.backup_dir)
                logger.info("| Removed existing backup directory")

            # Create fresh backup by copying entire test environment
            shutil.copytree(self.test_root, self.backup_dir)

            logger.info(
                "| ✓ Created backup for task %s: %s",
                task.name,
                self.backup_dir
            )
            return True

        except Exception as exc:  # pylint: disable=broad-exception-caught
            logger.error("Failed to create backup for task %s: %s", task.name, exc)
            return False

    def _restore_from_backup(self, task: Optional[BaseTask] = None) -> bool:
        """
        Restore the test environment from backup.

        Args:
            task: The task to restore after (optional, for logging)

        Returns:
            bool: True if restore successful
        """
        try:
            if not self.backup_dir or not self.backup_dir.exists():
                logger.error("No backup directory available for restore")
                return False

            # Remove current test environment
            if self.test_root.exists():
                shutil.rmtree(self.test_root)

            # Restore from backup
            shutil.copytree(self.backup_dir, self.test_root)

            # Clean up backup directory
            shutil.rmtree(self.backup_dir)
            self.backup_dir = None

            task_name = task.name if task else "unknown"
            logger.info(
                "✅ Restored test environment from backup after task %s",
                task_name
            )
            return True

        except Exception as exc:  # pylint: disable=broad-exception-caught
            task_name = task.name if task else "unknown"
            logger.error(
                "Failed to restore from backup after task %s: %s",
                task_name,
                exc
            )
            return False

    # =========================================================================
    # Abstract Method Implementations Required by BaseStateManager
    # =========================================================================

    def _create_initial_state(  # pylint: disable=unused-argument
        self, task: BaseTask
    ) -> Optional[Dict[str, Any]]:
        """Create initial state for a task.

        For filesystem, this is handled in set_up() method by creating task directories.
        Returns the task directory path as state info.
        """
        if self.current_task_dir and self.current_task_dir.exists():
            return {"task_directory": str(self.current_task_dir)}
        return None

    def _store_initial_state_info(
        self, task: BaseTask, state_info: Dict[str, Any]
    ) -> None:
        """Store initial state information in the task object.

        For filesystem, we store the test directory path.
        """
        if state_info and "task_directory" in state_info:
            if hasattr(task, "__dict__"):
                task.test_directory = state_info["task_directory"]

    def _cleanup_task_initial_state(  # pylint: disable=unused-argument
        self, task: BaseTask
    ) -> bool:
        """Clean up initial state for a specific task.

        For filesystem, this means removing the task directory.
        """
        if hasattr(task, "test_directory") and task.test_directory:
            task_dir = Path(task.test_directory)
            if task_dir.exists():
                try:
                    shutil.rmtree(task_dir)
                    logger.info("Cleaned up task directory: %s", task_dir)
                    return True
                except Exception as exc:  # pylint: disable=broad-exception-caught
                    logger.error("Failed to clean up task directory: %s", exc)
                    return False
        return True

    def _cleanup_single_resource(self, resource: Dict[str, Any]) -> bool:
        """Clean up a single tracked resource.

        For filesystem, resources are paths to files/directories.
        """
        if "path" in resource:
            resource_path = Path(resource["path"])
            if resource_path.exists():
                try:
                    if resource_path.is_dir():
                        shutil.rmtree(resource_path)
                    else:
                        resource_path.unlink()
                    logger.info("Cleaned up resource: %s", resource_path)
                    return True
                except Exception as exc:  # pylint: disable=broad-exception-caught
                    logger.error("Failed to clean up %s: %s", resource_path, exc)
                    return False
        return True

    def _download_and_extract_test_environment(  # pylint: disable=too-many-return-statements, too-many-branches
        self
    ) -> bool:
        """
        Download and extract test environment using wget and unzip commands.

        This approach preserves original file timestamps and is simpler than Python zipfile.

        Returns:
            bool: True if download and extraction successful
        """
        try:

            # Define URL mapping for different test environment categories
            url_mapping = {
                'desktop': 'https://storage.mcpmark.ai/filesystem/desktop.zip',
                'file_context': 'https://storage.mcpmark.ai/filesystem/file_context.zip',
                'file_property': 'https://storage.mcpmark.ai/filesystem/file_property.zip',
                'folder_structure': 'https://storage.mcpmark.ai/filesystem/folder_structure.zip',
                'papers': 'https://storage.mcpmark.ai/filesystem/papers.zip',
                'student_database': 'https://storage.mcpmark.ai/filesystem/student_database.zip',
                'threestudio': 'https://storage.mcpmark.ai/filesystem/threestudio.zip',
                'votenet': 'https://storage.mcpmark.ai/filesystem/votenet.zip',
                'legal_document': 'https://storage.mcpmark.ai/filesystem/legal_document.zip',
                'desktop_template': 'https://storage.mcpmark.ai/filesystem/desktop_template.zip'
            }

            # Get the category from the current task context
            category = getattr(self, '_current_task_category', None)
            if not category:
                logger.error("| No task category available for URL selection")
                return False

            # Select the appropriate URL based on category
            if category in url_mapping:
                test_env_url = url_mapping[category]
                logger.info(
                    "| ○ Selected URL for category '%s': %s",
                    category,
                    test_env_url
                )
            else:
                logger.error("| No URL mapping found for category: %s", category)
                return False

            # Allow override via environment variable
            test_env_url = os.getenv('TEST_ENVIRONMENT_URL', test_env_url)

            logger.info("| ○ Downloading test environment from: %s", test_env_url)

            # Create a temporary directory for the download
            with tempfile.TemporaryDirectory() as temp_dir:
                temp_path = Path(temp_dir)
                zip_path = temp_path / "test_environment.zip"

                # Step 1: Download using wget
                logger.info("| ○ Downloading test environment zip file...")
                try:
                    # Use wget if available, otherwise fall back to curl
                    if sys.platform == "win32":
                        # Windows: try wget, fall back to curl
                        try:
                            subprocess.run(
                                ["wget", "-O", str(zip_path), test_env_url],
                                capture_output=True, text=True, check=True
                            )
                        except (subprocess.CalledProcessError, FileNotFoundError):
                            # Fall back to curl
                            subprocess.run(
                                ["curl", "-L", "-o", str(zip_path), test_env_url],
                                capture_output=True, text=True, check=True
                            )
                    else:
                        # Unix-like systems: try wget, fall back to curl
                        try:
                            subprocess.run(
                                ["wget", "-O", str(zip_path), test_env_url],
                                capture_output=True, text=True, check=True
                            )
                        except (subprocess.CalledProcessError, FileNotFoundError):
                            # Fall back to curl
                            subprocess.run(
                                ["curl", "-L", "-o", str(zip_path), test_env_url],
                                capture_output=True, text=True, check=True
                            )

                    logger.info("| ✓ Download completed successfully")
                except Exception as exc:  # pylint: disable=broad-exception-caught
                    logger.error("| Download failed: %s", exc)
                    return False

                # Step 2: Extract using unzip
                logger.info("| ○ Extracting test environment...")
                try:
                    # Extract to parent directory to maintain expected structure
                    subprocess.run(
                        ["unzip", "-o", str(zip_path), "-d", str(self.test_root.parent)],
                        capture_output=True, text=True, check=True
                    )
                    logger.info("| ✓ Extraction completed successfully")
                except Exception as exc:  # pylint: disable=broad-exception-caught
                    logger.error("| Extraction failed: %s", exc)
                    return False

                # Step 3: Remove __MACOSX folder if it exists
                macosx_path = self.test_root.parent / "__MACOSX"
                self._remove_macosx_folder(macosx_path)

                # Verify the extracted directory exists
                if not self.test_root.exists():
                    logger.error(
                        "| Extracted directory not found at expected path: %s",
                        self.test_root
                    )
                    return False

                logger.info(
                    "| ✓ Successfully downloaded and extracted test environment to: %s",
                    self.test_root
                )
                return True

        except Exception as exc:  # pylint: disable=broad-exception-caught
            logger.error(
                "| Failed to download and extract test environment: %s",
                exc
            )
            return False
