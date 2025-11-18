"""
Cleanup functions for tasks.
"""
import asyncio
import random
import logging
from typing import Callable

import os
import requests  # pylint: disable=import-error
from mcpuniverse.common.context import Context

logger = logging.getLogger(__name__)

CLEANUP_FUNCTIONS = {}


def cleanup_func(server_name: str, cleanup_func_name: str):
    """A decorator for cleanup functions"""

    def _decorator(func: Callable):
        assert (server_name, cleanup_func_name) not in CLEANUP_FUNCTIONS, \
            f"Duplicated cleanup function ({server_name}, {cleanup_func_name})"
        CLEANUP_FUNCTIONS[(server_name, cleanup_func_name)] = func

        async def _wrapper(*args, **kwargs):
            return await func(*args, **kwargs)

        return _wrapper

    return _decorator


@cleanup_func("weather", "cleanup")
async def _weather_dummy(**kwargs):
    """A dummy cleanup function for testing purpose only."""
    return kwargs


@cleanup_func("google-maps", "cleanup")
async def _google_maps_dummy(**kwargs):
    """A dummy cleanup function for testing purpose only."""
    return kwargs


@cleanup_func("github", "delete_repository")
async def github_delete_repository(repo: str, owner: str = "", **kwargs):
    """
    Delete a github repository.
    https://docs.github.com/en/rest/repos/repos?apiVersion=2022-11-28#delete-a-repository

    Args:
        owner (str): Repository owner.
        repo (str): Repository name.
    """
    context = kwargs.get("context", Context())
    if owner == "":
        owner = context.get_env("GITHUB_PERSONAL_ACCOUNT_NAME")
    if owner == "":
        raise ValueError("Repository owner is empty")

    url = f"https://api.github.com/repos/{owner}/{repo}"
    headers = {
        "Authorization": f"Bearer {context.get_env('GITHUB_PERSONAL_ACCESS_TOKEN')}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "MCPUniverse"
    }
    delay_time = 1
    for _ in range(int(kwargs.get("max_retries", 3))):
        response = requests.delete(url, headers=headers, timeout=int(kwargs.get("timeout", 30)))
        if response.status_code == 204:
            return f"Repository {owner}/{repo} has been successfully deleted"
        if response.status_code == 403:
            raise RuntimeError(
                "Permission denied. You may not have delete permissions for "
                f"{owner}/{repo}."
            )
        if response.status_code == 404:
            raise RuntimeError(f"Repository {owner}/{repo} not found.")
        await asyncio.sleep(delay_time)
        delay_time *= random.uniform(1, 1.5)
    raise RuntimeError("`github_delete_repository` Reached the max retries")


@cleanup_func("notion", "delete_page")
async def notion_delete_page(page: str, _owner: str = "", **kwargs):
    """
    Move a Notion page to trash.
    https://developers.notion.com/reference/archive-a-page

    Args:
        page (str): Page ID.
    """
    context = kwargs.get("context", Context())
    url = f"https://api.notion.com/v1/pages/{page}"
    headers = {
        "Authorization": f"Bearer {context.get_env('NOTION_API_KEY')}",
        "Content-Type": "application/json",
        "Notion-Version": "2022-06-28",
    }

    data = '{"in_trash": true}'
    delay_time = 1
    for _ in range(int(kwargs.get("max_retries", 3))):
        response = requests.patch(
            url,
            headers=headers,
            data=data,
            timeout=int(kwargs.get("timeout", 30)),
        )
        if response.status_code == 200:
            return f"Page {page} has been successfully moved to trash"
        if response.status_code == 403:
            raise RuntimeError(
                "Permission denied. You may not have delete permissions for "
                f"{page}."
            )
        if response.status_code == 404:
            raise RuntimeError(f"Page {page} not found.")
        await asyncio.sleep(delay_time)
        delay_time *= random.uniform(1, 1.5)
    raise RuntimeError("`notion_delete_page` Reached the max retries")


# =============================================================================
# MCPMark State Manager Integration Functions
# =============================================================================

@cleanup_func("mcpmark", "github_cleanup")
async def mcpmark_github_cleanup(context: Context = None, **_kwargs):
    """
    Cleanup GitHub environment for MCPMark tasks.
    
    This function mimics the GitHubStateManager.clean_up() behavior:
    - Deletes created repositories
    - Cleans up evaluation workspace
    
    Args:
        context: Context object (automatically passed by framework)
        **kwargs: Additional arguments from cleanup_args in task config
    """
    try:
        if not context:
            logger.warning("No context provided for GitHub cleanup")
            return "No context for cleanup"

        # Get state manager from context
        state_manager = context.env.get("MCPMARK_GITHUB_STATE_MANAGER")
        task = context.env.get("MCPMARK_GITHUB_TASK")

        if not state_manager:
            logger.info(
                "No GitHub state manager found in context - "
                "likely setup was not performed or failed"
            )
            return "No state manager to cleanup"

        if not task:
            logger.warning("No task object found in context")
            return "No task object to cleanup"

        # Call cleanup
        logger.info("Cleaning up GitHub environment for task: %s", task.name)
        success = state_manager.clean_up(task)

        # Clear from context
        context.env.pop("MCPMARK_GITHUB_STATE_MANAGER", None)
        context.env.pop("MCPMARK_GITHUB_TASK", None)

        if success:
            logger.info("GitHub environment cleanup completed successfully")
            return "GitHub environment cleanup completed"
        logger.warning("GitHub cleanup completed with some failures")
        return "GitHub cleanup completed with warnings"

    except Exception as e:
        logger.error("Failed to cleanup GitHub environment: %s", e, exc_info=True)
        raise


@cleanup_func("mcpmark", "notion_cleanup")
async def mcpmark_notion_cleanup(context: Context = None, **_kwargs):
    """
    Cleanup Notion environment for MCPMark tasks.
    
    This function mimics the NotionStateManager.clean_up() behavior:
    - Deletes duplicated pages
    - Cleans up evaluation workspace
    
    Args:
        context: Context object (automatically passed by framework)
        **kwargs: Additional arguments from cleanup_args in task config
    """
    try:
        if not context:
            logger.warning("No context provided for Notion cleanup")
            return "No context for cleanup"

        # Get state manager from context
        state_manager = context.env.get("MCPMARK_NOTION_STATE_MANAGER")
        task = context.env.get("MCPMARK_NOTION_TASK")

        if not state_manager:
            logger.info(
                "No Notion state manager found in context - "
                "likely setup was not performed or failed"
            )
            return "No state manager to cleanup"

        if not task:
            logger.warning("No task object found in context")
            return "No task object to cleanup"

        # Call cleanup in a separate thread to avoid asyncio/Playwright conflict
        # Playwright sync API cannot run inside an asyncio loop
        logger.info("Cleaning up Notion environment for task: %s", task.name)
        success = await asyncio.to_thread(state_manager.clean_up, task)

        # Clear from context
        context.env.pop("MCPMARK_NOTION_STATE_MANAGER", None)
        context.env.pop("MCPMARK_NOTION_TASK", None)
        context.env.pop("MCPMARK_NOTION_PAGE_URL", None)
        # Note: We don't clear NOTION_API_KEY from context as it might be used by other tasks

        if success:
            logger.info("Notion environment cleanup completed successfully")
            return "Notion environment cleanup completed"
        logger.warning("Notion cleanup completed with some failures")
        return "Notion cleanup completed with warnings"

    except Exception as e:
        logger.error("Failed to cleanup Notion environment: %s", e, exc_info=True)
        raise


@cleanup_func("mcpmark", "filesystem_cleanup")
async def mcpmark_filesystem_cleanup(context: Context = None, **_kwargs):
    """
    Cleanup Filesystem environment for MCPMark tasks.
    
    This function mimics the FilesystemStateManager.clean_up() behavior:
    - Cleans up backup directories
    - Removes temporary resources
    
    Args:
        context: Context object (automatically passed by framework)
        **kwargs: Additional arguments from cleanup_args in task config
    """
    try:
        if not context:
            logger.warning("No context provided for Filesystem cleanup")
            return "No context for cleanup"

        # Get state manager from context
        state_manager = context.env.get("MCPMARK_FILESYSTEM_STATE_MANAGER")
        task = context.env.get("MCPMARK_FILESYSTEM_TASK")

        if not state_manager:
            logger.info(
                "No Filesystem state manager found in context - "
                "likely setup was not performed or failed"
            )
            return "No state manager to cleanup"

        if not task:
            logger.warning("No task object found in context")
            return "No task object to cleanup"

        # Call cleanup in a separate thread for consistency
        logger.info("Cleaning up Filesystem environment for task: %s", task.name)
        success = await asyncio.to_thread(state_manager.clean_up, task)

        # Clear from context
        context.env.pop("MCPMARK_FILESYSTEM_STATE_MANAGER", None)
        context.env.pop("MCPMARK_FILESYSTEM_TASK", None)
        context.env.pop("MCPMARK_FILESYSTEM_TEST_DIR", None)

        if success:
            logger.info("Filesystem environment cleanup completed successfully")
            return "Filesystem environment cleanup completed"
        logger.warning("Filesystem cleanup completed with some failures")
        return "Filesystem cleanup completed with warnings"

    except Exception as e:
        logger.error("Failed to cleanup Filesystem environment: %s", e, exc_info=True)
        raise


@cleanup_func("mcpmark", "playwright_cleanup")
async def mcpmark_playwright_cleanup(context: Context = None, **_kwargs):
    """
    Cleanup Playwright environment for MCPMark tasks.
    
    Playwright cleanup is minimal - just clears tracked resources.
    No browser state needs to be cleaned up.
    
    Args:
        context: Context object (automatically passed by framework)
        **kwargs: Additional arguments from cleanup_args in task config
    """
    try:
        if not context:
            logger.warning("No context provided for Playwright cleanup")
            return "No context for cleanup"

        # Get state manager from context
        state_manager = context.env.get("MCPMARK_PLAYWRIGHT_STATE_MANAGER")
        task = context.env.get("MCPMARK_PLAYWRIGHT_TASK")

        if not state_manager:
            logger.info(
                "No Playwright state manager found in context - "
                "likely setup was not performed or failed"
            )
            return "No state manager to cleanup"

        if not task:
            logger.warning("No task object found in context")
            return "No task object to cleanup"

        # Call cleanup - Playwright cleanup is lightweight (just clears resources)
        logger.info("Cleaning up Playwright environment for task: %s", task.name)
        success = state_manager.clean_up(task)

        # Clear from context
        context.env.pop("MCPMARK_PLAYWRIGHT_STATE_MANAGER", None)
        context.env.pop("MCPMARK_PLAYWRIGHT_TASK", None)
        context.env.pop("MCPMARK_PLAYWRIGHT_TEST_URL", None)
        context.env.pop("MCP_MESSAGES", None)

        # Clean up MCP_MESSAGES from os.environ as well
        os.environ.pop("MCP_MESSAGES", None)

        if success:
            logger.info("Playwright environment cleanup completed successfully")
            return "Playwright environment cleanup completed"
        logger.warning("Playwright cleanup completed with some failures")
        return "Playwright cleanup completed with warnings"

    except Exception as e:
        logger.error("Failed to cleanup Playwright environment: %s", e, exc_info=True)
        raise


@cleanup_func("mcpmark", "playwright_webarena_cleanup")
async def mcpmark_playwright_webarena_cleanup(context: Context = None, **_kwargs):
    """
    Cleanup Playwright WebArena environment for MCPMark tasks.
    
    This function:
    - Stops and removes Docker containers
    - Cleans up WebArena environment
    
    Args:
        context: Context object (automatically passed by framework)
        **kwargs: Additional arguments from cleanup_args in task config
    """
    try:
        if not context:
            logger.warning("No context provided for Playwright WebArena cleanup")
            return "No context for cleanup"

        # Get state manager from context
        state_manager = context.env.get("MCPMARK_PLAYWRIGHT_WEBARENA_STATE_MANAGER")
        task = context.env.get("MCPMARK_PLAYWRIGHT_WEBARENA_TASK")

        if not state_manager:
            logger.info(
                "No Playwright WebArena state manager found in context - "
                "likely setup was not performed or failed"
            )
            return "No state manager to cleanup"

        if not task:
            logger.warning("No task object found in context")
            return "No task object to cleanup"

        # Call cleanup in a separate thread (Docker operations are synchronous)
        logger.info(
            "Cleaning up Playwright WebArena environment for task: %s",
            task.name,
        )
        success = await asyncio.to_thread(state_manager.clean_up, task)

        # Clear from context
        context.env.pop("MCPMARK_PLAYWRIGHT_WEBARENA_STATE_MANAGER", None)
        context.env.pop("MCPMARK_PLAYWRIGHT_WEBARENA_TASK", None)
        context.env.pop("MCPMARK_PLAYWRIGHT_WEBARENA_URL", None)
        context.env.pop("MCP_MESSAGES", None)

        # Clean up MCP_MESSAGES from os.environ as well
        os.environ.pop("MCP_MESSAGES", None)

        if success:
            logger.info("Playwright WebArena environment cleanup completed successfully")
            return "Playwright WebArena environment cleanup completed"
        logger.warning("Playwright WebArena cleanup completed with some failures")
        return "Playwright WebArena cleanup completed with warnings"

    except Exception as e:
        logger.error(
            "Failed to cleanup Playwright WebArena environment: %s",
            e,
            exc_info=True,
        )
        raise


@cleanup_func("mcpmark", "postgres_cleanup")
async def mcpmark_postgres_cleanup(context: Context = None, **_kwargs):
    """
    Cleanup Postgres environment for MCPMark tasks.
    
    This function:
    - Drops the task-specific database
    - Cleans up environment variables
    
    Args:
        context: Context object (automatically passed by framework)
        **kwargs: Additional arguments from cleanup_args in task config
    """
    try:
        if not context:
            logger.warning("No context provided for Postgres cleanup")
            return "No context for cleanup"

        # Get state manager from context
        state_manager = context.env.get("MCPMARK_POSTGRES_STATE_MANAGER")
        task = context.env.get("MCPMARK_POSTGRES_TASK")

        if not state_manager:
            logger.info(
                "No Postgres state manager found in context - "
                "likely setup was not performed or failed"
            )
            return "No state manager to cleanup"

        if not task:
            logger.warning("No task object found in context")
            return "No task object to cleanup"

        logger.info("Cleaning up Postgres environment for task: %s", task.name)

        # Call cleanup (synchronous but fast)
        success = state_manager.clean_up(task)

        # Clear from context
        context.env.pop("MCPMARK_POSTGRES_STATE_MANAGER", None)
        context.env.pop("MCPMARK_POSTGRES_TASK", None)
        context.env.pop("POSTGRES_DATABASE", None)
        context.env.pop("POSTGRES_DATABASE_URL", None)

        # Clean up environment variables
        os.environ.pop("POSTGRES_DATABASE", None)
        os.environ.pop("POSTGRES_DATABASE_URL", None)

        if success:
            logger.info("Postgres environment cleanup completed successfully")
            return "Postgres environment cleanup completed"
        logger.warning("Postgres cleanup completed with some failures")
        return "Postgres cleanup completed with warnings"

    except Exception as e:
        logger.error("Failed to cleanup Postgres environment: %s", e, exc_info=True)
        raise
