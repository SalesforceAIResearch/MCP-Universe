"""
Preparation functions for tasks.
"""
import os
import logging
import importlib.util
import subprocess
import tempfile
import shutil
import time
import asyncio
from pathlib import Path
from typing import Callable

from mcpuniverse.common.context import Context

PREPARE_FUNCTIONS = {}

logger = logging.getLogger(__name__)


def _add_mcpmark_to_path():
    """Add mcpmark dependencies directory to Python path for imports."""
    import sys  # pylint: disable=import-outside-toplevel
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


def prepare_func(prepare_func_name: str):
    """A decorator for preparation functions"""

    def _decorator(func: Callable):
        assert prepare_func_name not in PREPARE_FUNCTIONS, \
            f"Duplicated prepare function: {prepare_func_name}"
        PREPARE_FUNCTIONS[prepare_func_name] = func

        async def _wrapper(*args, **kwargs):
            return await func(*args, **kwargs)

        return _wrapper

    return _decorator


@prepare_func("set_postgres_database")
async def set_postgres_database(
    context: Context = None,
    database: str = None,
    category: str = None,
    **_kwargs
):
    """
    Dynamically set POSTGRES_DATABASE and POSTGRES_ADDRESS for a specific database.

    This function will automatically use the task's category as the database name
    if database is not specified.

    Args:
        context: Execution context
        database: Explicit database name (e.g., 'chinook', 'employees', 'dvdrental')
        category: Task category (will be used as database name if database is not specified)
    """
    # Use category as database name if database is not specified
    db_name = database or category

    if not db_name:
        logger.warning("No database or category specified for set_postgres_database")
        return

    # Update environment variables
    os.environ["POSTGRES_DATABASE"] = db_name

    # Update POSTGRES_ADDRESS to use the new database
    postgres_address = os.getenv("POSTGRES_ADDRESS", "")
    new_address = None
    if postgres_address:
        # Replace database name in connection string
        # Format: postgresql://user:pass@host:port/old_database
        parts = postgres_address.rsplit("/", 1)
        if len(parts) == 2:
            base_url = parts[0]
            # Remove query parameters if any from old database
            if "?" in parts[1]:
                query_params = "?" + parts[1].split("?")[1]
            else:
                query_params = ""
            new_address = f"{base_url}/{db_name}{query_params}"
            os.environ["POSTGRES_ADDRESS"] = new_address
            logger.info(
                "Set POSTGRES_DATABASE to '%s' and updated POSTGRES_ADDRESS",
                db_name
            )

    # Update context if provided
    if context:
        context.env["POSTGRES_DATABASE"] = db_name
        if postgres_address and new_address:
            context.env["POSTGRES_ADDRESS"] = new_address

    return f"PostgreSQL database set to: {db_name}"


@prepare_func("prepare_vector_database")
async def prepare_vector_database(context: Context = None, **_kwargs):  # pylint: disable=unused-argument
    """
    Prepare vector database environment by running the prepare_environment.py script.

    This function dynamically imports and executes the prepare_environment function
    from the specified verification files directory.
    """
    try:
        # Path to the prepare_environment script
        script_path = (
            Path(__file__).parent / "configs" / "test" / "mcpmark" /
            "postgres_verification_files" / "dba_vector_analysis_prepare_environment.py"
        )

        if not script_path.exists():
            raise FileNotFoundError(
                f"Prepare environment script not found: {script_path}"
            )

        # Dynamically import the module
        spec = importlib.util.spec_from_file_location("dba_vector_prepare", script_path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        # Execute the prepare_environment function
        if hasattr(module, 'prepare_environment'):
            logger.info("Executing prepare_environment for vector database...")
            module.prepare_environment()
            return "Vector database environment prepared successfully"
        raise AttributeError("prepare_environment function not found in script")

    except Exception as exc:
        logger.error("Failed to prepare vector database: %s", exc)
        raise


@prepare_func("prepare_rls_business_access")
async def prepare_rls_business_access(context: Context = None, **_kwargs):  # pylint: disable=unused-argument
    """
    Prepare RLS business access environment by running the prepare_environment.py script.
    """
    try:
        script_path = Path(__file__).parent / "configs" / "test" / "mcpmark" / \
                     "postgres_verification_files" / "rls_business_access_prepare_environment.py"

        if not script_path.exists():
            raise FileNotFoundError(
                f"Prepare environment script not found: {script_path}"
            )

        spec = importlib.util.spec_from_file_location("rls_prepare", script_path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        if hasattr(module, 'prepare_environment'):
            logger.info("Executing prepare_environment for RLS business access...")
            module.prepare_environment()
            return "RLS business access environment prepared successfully"
        raise AttributeError("prepare_environment function not found in script")

    except Exception as exc:
        logger.error("Failed to prepare RLS business access: %s", exc)
        raise


@prepare_func("prepare_user_permission_audit")
async def prepare_user_permission_audit(context: Context = None, **_kwargs):  # pylint: disable=unused-argument
    """
    Prepare user permission audit environment by running the prepare_environment.py script.
    """
    try:
        script_path = Path(__file__).parent / "configs" / "test" / "mcpmark" / \
                     "postgres_verification_files" / "user_permission_audit_prepare_environment.py"

        if not script_path.exists():
            raise FileNotFoundError(
                f"Prepare environment script not found: {script_path}"
            )

        spec = importlib.util.spec_from_file_location("user_permission_prepare", script_path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        if hasattr(module, 'prepare_environment'):
            logger.info("Executing prepare_environment for user permission audit...")
            module.prepare_environment()
            return "User permission audit environment prepared successfully"
        raise AttributeError("prepare_environment function not found in script")

    except Exception as exc:
        logger.error("Failed to prepare user permission audit: %s", exc)
        raise


@prepare_func("download_filesystem_environment")
async def download_filesystem_environment(  # pylint: disable=too-many-statements, too-many-branches
    context: Context = None,
    category: str = None,
    **_kwargs
):
    """
    Download and extract filesystem test environment for MCPMark tasks.

    This function automatically downloads the test environment from storage.mcpmark.ai
    if it doesn't already exist locally. It mimics mcpmark's FilesystemStateManager
    auto-download functionality.

    Args:
        context: Execution context
        category: Environment category (e.g., 'desktop', 'papers', 'threestudio')
                 If not specified, uses task category from context

    Returns:
        str: Success message with download location

    Raises:
        ValueError: If category is unknown
        RuntimeError: If download or extraction fails
    """
    # URL mapping for different test environment categories
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

    # Use category from kwargs or context
    if not category:
        category = _kwargs.get('category')

    if not category:
        raise ValueError("Category must be specified for filesystem environment download")

    if category not in url_mapping:
        raise ValueError(
            f"Unknown category: {category}. "
            f"Supported: {', '.join(url_mapping.keys())}"
        )

    # Determine test root directory
    if context:
        test_root_str = context.get_env("FILESYSTEM_TEST_ROOT", "")
    else:
        test_root_str = os.getenv("FILESYSTEM_TEST_ROOT", "")

    if test_root_str:
        base_test_path = Path(test_root_str)
    else:
        # Default to project_root/test_environments
        project_root = Path(__file__).resolve().parents[2]
        base_test_path = project_root / "test_environments"

    target_dir = base_test_path / category

    # Check if already exists
    if target_dir.exists():
        logger.info("Test environment already exists: %s", target_dir)
        # Update context with the path
        if context:
            context.env["FILESYSTEM_TEST_DIR"] = str(target_dir)
        return f"Using existing environment: {target_dir}"

    logger.info("Downloading filesystem test environment: %s", category)

    try:
        # Ensure parent directory exists
        base_test_path.mkdir(parents=True, exist_ok=True)

        # Get download URL
        url = url_mapping[category]
        url = os.getenv('TEST_ENVIRONMENT_URL', url)  # Allow override

        logger.info("| ○ Downloading from: %s", url)

        # Create temporary directory for download
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            zip_path = temp_path / f"{category}.zip"

            # Step 1: Download using wget or curl
            logger.info("| ○ Downloading zip file...")
            try:
                # Try wget first
                try:
                    subprocess.run(
                        ["wget", "-O", str(zip_path), url],
                        capture_output=True,
                        text=True,
                        check=True
                    )
                    logger.info("| ✓ Download completed (wget)")
                except (subprocess.CalledProcessError, FileNotFoundError):
                    # Fallback to curl
                    subprocess.run(
                        ["curl", "-L", "-o", str(zip_path), url],
                        capture_output=True,
                        text=True,
                        check=True
                    )
                    logger.info("| ✓ Download completed (curl)")
            except subprocess.CalledProcessError as exc:
                raise RuntimeError(f"Download failed: {exc.stderr}") from exc

            # Step 2: Extract using unzip
            logger.info("| ○ Extracting test environment...")
            try:
                subprocess.run(
                    ["unzip", "-o", str(zip_path), "-d", str(base_test_path)],
                    capture_output=True,
                    text=True,
                    check=True
                )
                logger.info("| ✓ Extraction completed")
            except subprocess.CalledProcessError as exc:
                raise RuntimeError(f"Extraction failed: {exc.stderr}") from exc
            except FileNotFoundError as exc:
                raise RuntimeError(
                    "unzip command not found. Please install unzip."
                ) from exc

            # Step 3: Cleanup macOS metadata
            logger.info("| ○ Cleaning up macOS metadata...")
            macosx_path = base_test_path / "__MACOSX"
            if macosx_path.exists():
                shutil.rmtree(macosx_path)
                logger.info("| ✓ Removed __MACOSX folder")

            # Step 4: Verify extraction
            if not target_dir.exists():
                raise RuntimeError(f"Extracted directory not found: {target_dir}")

            logger.info("| ✓ Successfully downloaded: %s", target_dir)

            # Update context with the path
            if context:
                context.env["FILESYSTEM_TEST_DIR"] = str(target_dir)

            return f"Downloaded and extracted: {target_dir}"

    except Exception as exc:
        logger.error("Failed to download filesystem environment: %s", exc)
        raise


# =============================================================================
# MCPMark State Manager Integration Functions
# =============================================================================

@prepare_func("mcpmark_github_setup")
async def mcpmark_github_setup(
    context: Context = None,
    category: str = None,
    **_kwargs
):
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

        # Import mcpmark modules (dynamic import, path added at runtime)
        from third_party.mcpmark.src.mcp_services.github.github_state_manager import (  # pylint: disable=import-error, import-outside-toplevel
            GitHubStateManager
        )

        # Get GitHub token from context
        if not context:
            raise ValueError("Context required for GitHub setup")

        github_token = context.get_env("GITHUB_TOKENS")
        if not github_token:
            raise ValueError("GITHUB_TOKENS required")

        # Create a mock task object with proper attributes
        class MockTask:  # pylint: disable=too-few-public-methods
            """Lightweight task placeholder for GitHubStateManager interaction."""

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

            logger.info(
                "GitHub environment setup completed for task: %s",
                mock_task.name
            )
            return f"GitHub environment setup completed for task: {mock_task.name}"
        raise RuntimeError("GitHub setup failed")

    except Exception as exc:
        logger.error("Failed to setup GitHub environment: %s", exc)
        raise


@prepare_func("mcpmark_notion_setup")
async def mcpmark_notion_setup(
    context: Context = None,
    category: str = None,
    **_kwargs
):
    """
    Setup Notion environment for MCPMark tasks.

    This function mimics the NotionStateManager.set_up() behavior:
    - Duplicates Notion pages for task isolation
    - Sets up evaluation workspace

    Args:
        context: Execution context (automatically passed by mcpuniverse)
        category: Task category (automatically passed by mcpuniverse)
        **kwargs: Additional arguments from prepare_args
    """
    try:
        # Add mcpmark to path
        _add_mcpmark_to_path()

        # Import mcpmark modules (dynamic import, path added at runtime)
        from src.mcp_services.notion.notion_state_manager import (  # pylint: disable=import-error, import-outside-toplevel
            NotionStateManager
        )
        from src.mcp_services.notion.notion_task_manager import (  # pylint: disable=import-error, import-outside-toplevel
            NotionTask
        )

        # Get Notion API keys from context
        if not context:
            raise ValueError("Context required for Notion setup")

        source_key = context.get_env("SOURCE_NOTION_API_KEY")
        eval_key = context.get_env("EVAL_NOTION_API_KEY")

        if not source_key or not eval_key:
            raise ValueError("SOURCE_NOTION_API_KEY and EVAL_NOTION_API_KEY required")

        # Generate a unique task ID based on category and timestamp
        task_id = f"task_{int(time.time())}"

        # Create a NotionTask object - NotionTask is a dataclass
        # We need to provide dummy paths since they're not used in setup
        dummy_path = Path("dummy")

        mock_task = NotionTask(
            task_instruction_path=dummy_path,
            task_verification_path=dummy_path,
            service="notion",
            category_id=category or "company_in_a_box",
            task_id=task_id,
            task_name=f"mcpuniverse_task_{task_id}",
            original_initial_state_url=None,
            duplicated_initial_state_url=None,
            duplicated_initial_state_id=None
        )

        logger.info("Setting up Notion environment for task: %s", mock_task.name)

        # Initialize state manager
        state_manager = NotionStateManager(
            source_notion_key=source_key,
            eval_notion_key=eval_key,
            headless=context.get_env("NOTION_HEADLESS", "true").lower() == "true",
            browser=context.get_env("NOTION_BROWSER", "firefox")
        )

        # Call setup in a separate thread to avoid asyncio/Playwright conflict
        # Playwright sync API cannot run inside an asyncio loop
        success = await asyncio.to_thread(state_manager.set_up, mock_task)

        if success:
            # Store state manager in context for cleanup
            if context:
                context.env["MCPMARK_NOTION_STATE_MANAGER"] = state_manager
                context.env["MCPMARK_NOTION_TASK"] = mock_task
                # Store the page URL for potential use by evaluators
                if (hasattr(mock_task, 'duplicated_initial_state_url') and
                        mock_task.duplicated_initial_state_url):
                    context.env["MCPMARK_NOTION_PAGE_URL"] = (
                        mock_task.duplicated_initial_state_url
                    )

            logger.info(
                "Notion environment setup completed for task: %s",
                mock_task.name
            )
            return f"Notion environment setup completed for task: {mock_task.name}"
        raise RuntimeError("Notion setup failed")

    except Exception as exc:
        logger.error("Failed to setup Notion environment: %s", exc)
        raise


@prepare_func("mcpmark_filesystem_setup")
async def mcpmark_filesystem_setup(
    context: Context = None,
    category: str = None,
    **_kwargs
):
    """
    Setup Filesystem environment for MCPMark tasks.

    This function mimics the FilesystemStateManager.set_up() behavior:
    - Creates backup of test environment
    - Sets up isolated working directory
    - Configures environment variables

    Args:
        context: Execution context (automatically passed by mcpuniverse)
        category: Task category (automatically passed by mcpuniverse)
        **kwargs: Additional arguments from prepare_args
    """
    try:
        # Add mcpmark to path
        _add_mcpmark_to_path()

        # Import mcpmark modules (dynamic import, path added at runtime)
        from src.mcp_services.filesystem.filesystem_state_manager import (  # pylint: disable=import-error, import-outside-toplevel
            FilesystemStateManager
        )

        # Get test root from context if available
        if context:
            test_root = context.get_env("FILESYSTEM_TEST_ROOT", "")
        else:
            test_root = os.getenv("FILESYSTEM_TEST_ROOT", "")

        # Create a mock task object with proper attributes
        class MockTask:  # pylint: disable=too-few-public-methods
            """Lightweight task placeholder for FilesystemStateManager interaction."""

            def __init__(self, category_id, task_id=None):
                self.category_id = category_id
                self.task_id = task_id or f"mcpuniverse_task_{category_id}"
                self.name = f"{category_id}__{self.task_id}"
                self.service = "filesystem"
                # Filesystem-specific attributes
                self.test_directory = None  # Will be set by state manager

        # Generate a unique task ID based on category and timestamp
        task_id = f"task_{int(time.time())}"
        mock_task = MockTask(category or "desktop", task_id)

        logger.info("Setting up Filesystem environment for task: %s", mock_task.name)

        # Initialize state manager
        state_manager = FilesystemStateManager(
            test_root=Path(test_root) if test_root else None
        )

        # Call setup in a separate thread (though filesystem doesn't use async, being consistent)
        success = await asyncio.to_thread(state_manager.set_up, mock_task)

        if success:
            # Store state manager in context for cleanup
            if context:
                context.env["MCPMARK_FILESYSTEM_STATE_MANAGER"] = state_manager
                context.env["MCPMARK_FILESYSTEM_TASK"] = mock_task
                # Store the test directory for potential use by evaluators
                if hasattr(mock_task, 'test_directory') and mock_task.test_directory:
                    context.env["MCPMARK_FILESYSTEM_TEST_DIR"] = mock_task.test_directory

            logger.info("Filesystem environment setup completed for task: %s", mock_task.name)
            return f"Filesystem environment setup completed for task: {mock_task.name}"
        raise RuntimeError("Filesystem setup failed")

    except Exception as exc:
        logger.error("Failed to setup Filesystem environment: %s", exc)
        raise


@prepare_func("mcpmark_playwright_setup")
async def mcpmark_playwright_setup(
    context: Context = None,
    category: str = None,
    **_kwargs
):
    """
    Setup Playwright environment for MCPMark tasks.

    Playwright tasks don't need actual state duplication - just track metadata.
    The PlaywrightStateManager creates a stub state for resource tracking.

    Args:
        context: Execution context (automatically passed by mcpuniverse)
        category: Task category (automatically passed by mcpuniverse)
        **kwargs: Additional arguments from prepare_args
    """
    try:
        # Add mcpmark to path
        _add_mcpmark_to_path()

        # Import mcpmark modules (dynamic import, path added at runtime)
        from src.mcp_services.playwright.playwright_state_manager import (  # pylint: disable=import-error, import-outside-toplevel
            PlaywrightStateManager
        )

        # Create a mock task object with proper attributes
        class MockTask:  # pylint: disable=too-few-public-methods
            """Lightweight task placeholder for PlaywrightStateManager interaction."""

            def __init__(self, category_id, task_id=None):
                self.category_id = category_id
                self.task_id = task_id or f"mcpuniverse_task_{category_id}"
                self.name = f"{category_id}__{self.task_id}"
                self.service = "playwright"
                # Playwright-specific attributes
                self.browser_context_id = None
                self.test_url = None
                self.browser_config = None

        # Generate a unique task ID based on category and timestamp
        task_id = f"task_{int(time.time())}"
        mock_task = MockTask(category or "eval_web", task_id)

        logger.info("Setting up Playwright environment for task: %s", mock_task.name)

        # Initialize state manager
        browser = "chromium"
        headless = True
        if context:
            browser = context.get_env("PLAYWRIGHT_BROWSER", "chromium")
            headless = context.get_env("PLAYWRIGHT_HEADLESS", "true").lower() == "true"
        state_manager = PlaywrightStateManager(browser=browser, headless=headless)

        # Call setup (creates stub state for tracking)
        # No async/sync conflict here since it just creates metadata
        success = state_manager.set_up(mock_task)

        if success:
            # Store state manager in context for cleanup
            if context:
                context.env["MCPMARK_PLAYWRIGHT_STATE_MANAGER"] = state_manager
                context.env["MCPMARK_PLAYWRIGHT_TASK"] = mock_task
                # Store test URL if available
                if hasattr(mock_task, 'test_url') and mock_task.test_url:
                    context.env["MCPMARK_PLAYWRIGHT_TEST_URL"] = mock_task.test_url

                # Set MCP_MESSAGES environment variable for verification scripts
                # Create a placeholder messages.json path (will be created during execution)
                temp_dir = Path(tempfile.gettempdir()) / "mcpmark_playwright"
                temp_dir.mkdir(exist_ok=True)
                messages_path = temp_dir / "messages.json"
                context.env["MCP_MESSAGES"] = str(messages_path)
                os.environ["MCP_MESSAGES"] = str(messages_path)
                logger.info("Set MCP_MESSAGES to: %s", messages_path)

            logger.info(
                "Playwright environment setup completed for task: %s",
                mock_task.name
            )
            return f"Playwright environment setup completed for task: {mock_task.name}"
        raise RuntimeError("Playwright setup failed")

    except Exception as exc:
        logger.error("Failed to setup Playwright environment: %s", exc)
        raise


@prepare_func("mcpmark_playwright_webarena_setup")
async def mcpmark_playwright_webarena_setup(
    context: Context = None,
    category: str = None,
    **_kwargs
):
    """
    Setup Playwright WebArena environment for MCPMark tasks.

    This function:
    - Starts Docker containers for WebArena environments
    - Configures the environment (e.g., shopping_admin, reddit)
    - Waits for services to be ready

    Args:
        context: Execution context (automatically passed by mcpuniverse)
        category: Task category (automatically passed by mcpuniverse)
        **kwargs: Additional arguments from prepare_args
    """
    try:
        # Add mcpmark to path
        _add_mcpmark_to_path()

        # Import mcpmark modules (dynamic import, path added at runtime)
        from src.mcp_services.playwright_webarena.playwright_state_manager import (  # pylint: disable=import-error, import-outside-toplevel
            PlaywrightStateManager
        )

        # Create a mock task object with proper attributes
        class MockTask:  # pylint: disable=too-few-public-methods
            """Lightweight task placeholder for PlaywrightWebArenaStateManager interaction."""

            def __init__(self, category_id, task_id=None):
                self.category_id = category_id
                self.task_id = task_id or f"mcpuniverse_task_{category_id}"
                self.name = f"{category_id}__{self.task_id}"
                self.service = "playwright_webarena"
                # WebArena-specific attributes
                self.docker_container_name = None
                self.base_url = None
                self.docker_metadata = None

        # Generate a unique task ID based on category and timestamp
        task_id = f"task_{int(time.time())}"
        mock_task = MockTask(category or "shopping_admin", task_id)

        logger.info(
            "Setting up Playwright WebArena environment for task: %s",
            mock_task.name
        )

        # Initialize state manager
        state_manager = PlaywrightStateManager()

        # Call setup in a separate thread (Docker operations are synchronous)
        success = await asyncio.to_thread(state_manager.set_up, mock_task)

        if success:
            # Store state manager in context for cleanup
            if context:
                context.env["MCPMARK_PLAYWRIGHT_WEBARENA_STATE_MANAGER"] = state_manager
                context.env["MCPMARK_PLAYWRIGHT_WEBARENA_TASK"] = mock_task
                # Store base URL for potential use by evaluators
                if hasattr(mock_task, 'base_url') and mock_task.base_url:
                    context.env["MCPMARK_PLAYWRIGHT_WEBARENA_URL"] = mock_task.base_url

                # Set MCP_MESSAGES environment variable for verification scripts
                temp_dir = Path(tempfile.gettempdir()) / "mcpmark_playwright_webarena"
                temp_dir.mkdir(exist_ok=True)
                messages_path = temp_dir / "messages.json"
                context.env["MCP_MESSAGES"] = str(messages_path)
                os.environ["MCP_MESSAGES"] = str(messages_path)
                logger.info("Set MCP_MESSAGES to: %s", messages_path)

            logger.info(
                "Playwright WebArena environment setup completed for task: %s",
                mock_task.name
            )
            return (
                f"Playwright WebArena environment setup completed for task: "
                f"{mock_task.name}"
            )
        raise RuntimeError("Playwright WebArena setup failed")

    except Exception as exc:
        logger.error("Failed to setup Playwright WebArena environment: %s", exc)
        raise


@prepare_func("mcpmark_postgres_setup")
async def mcpmark_postgres_setup(
    context: Context = None,
    category: str = None,
    **_kwargs
):
    """
    Setup Postgres environment for MCPMark tasks.

    This function:
    - Creates a task-specific database from category template (e.g., chinook, employees)
    - Sets environment variables for MCP server and evaluators

    Args:
        context: Execution context (automatically passed by mcpuniverse)
        category: Task category (automatically passed by mcpuniverse)
        **kwargs: Additional arguments from prepare_args
    """
    try:
        # Add mcpmark to path
        _add_mcpmark_to_path()

        # Import mcpmark modules (dynamic import, path added at runtime)
        from src.mcp_services.postgres.postgres_state_manager import (  # pylint: disable=import-error, import-outside-toplevel
            PostgresStateManager
        )

        # Get Postgres connection parameters from environment
        postgres_host = os.environ.get("POSTGRES_HOST", "localhost")
        postgres_port = int(os.environ.get("POSTGRES_PORT", "5432"))
        postgres_username = os.environ.get("POSTGRES_USERNAME", "postgres")
        postgres_password = os.environ.get("POSTGRES_PASSWORD", "")

        # Create a mock task object with proper attributes
        class MockTask:  # pylint: disable=too-few-public-methods
            """Lightweight task placeholder for PostgresStateManager interaction."""

            def __init__(self, category_id, task_id=None):
                self.category_id = category_id
                self.task_id = task_id or f"mcpuniverse_task_{category_id}"
                self.name = f"{category_id}__{self.task_id}"
                self.service = "postgres"
                # Postgres-specific attributes
                self.database_name = None
                self.database_url = None
                self.task_instruction_path = Path(".")  # Dummy path for prepare_environment.py

        # Generate a unique task ID based on category and timestamp
        task_id = f"task_{int(time.time())}"
        mock_task = MockTask(category or "postgres", task_id)

        logger.info("Setting up Postgres environment for task: %s", mock_task.name)

        # Initialize state manager
        state_manager = PostgresStateManager(
            host=postgres_host,
            port=postgres_port,
            username=postgres_username,
            password=postgres_password,
        )

        # Call setup (this is synchronous but fast)
        success = state_manager.set_up(mock_task)

        if success:
            # Store state manager in context for cleanup
            if context:
                context.env["MCPMARK_POSTGRES_STATE_MANAGER"] = state_manager
                context.env["MCPMARK_POSTGRES_TASK"] = mock_task

                # Set environment variables for MCP server and evaluators
                if hasattr(mock_task, 'database_name') and mock_task.database_name:
                    # Update POSTGRES_DATABASE for MCP server
                    context.env["POSTGRES_DATABASE"] = mock_task.database_name
                    os.environ["POSTGRES_DATABASE"] = mock_task.database_name
                    logger.info(
                        "Set POSTGRES_DATABASE to: %s",
                        mock_task.database_name
                    )

                    # Also set database URL for convenience
                    if hasattr(mock_task, 'database_url'):
                        context.env["POSTGRES_DATABASE_URL"] = mock_task.database_url
                        os.environ["POSTGRES_DATABASE_URL"] = mock_task.database_url

            logger.info(
                "Postgres environment setup completed for task: %s",
                mock_task.name
            )
            logger.info("Database created: %s", mock_task.database_name)
            return (
                f"Postgres environment setup completed. "
                f"Database: {mock_task.database_name}"
            )
        raise RuntimeError("Postgres setup failed")

    except Exception as exc:
        logger.error("Failed to setup Postgres environment: %s", exc)
        raise
