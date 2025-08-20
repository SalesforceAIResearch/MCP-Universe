"""
Cleanup functions for tasks.
"""
# pylint: disable=unused-argument
import asyncio
import random
from typing import Callable

import requests
from mcpuniverse.common.context import Context

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
            raise RuntimeError(f"Permission denied. You may not have delete permissions for {owner}/{repo}.")
        if response.status_code == 404:
            raise RuntimeError(f"Repository {owner}/{repo} not found.")
        await asyncio.sleep(delay_time)
        delay_time *= random.uniform(1, 1.5)
    raise RuntimeError("`github_delete_repository` Reached the max retries")


@cleanup_func("notion", "delete_page")
async def notion_delete_page(page: str, owner: str = "", **kwargs):
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
        response = requests.patch(url, headers=headers, data=data, timeout=int(kwargs.get("timeout", 30)))
        if response.status_code == 200:
            return f"Page {page} has been successfully moved to trash"
        if response.status_code == 403:
            raise RuntimeError(f"Permission denied. You may not have delete permissions for {page}.")
        if response.status_code == 404:
            raise RuntimeError(f"Page {page} not found.")
        await asyncio.sleep(delay_time)
        delay_time *= random.uniform(1, 1.5)
    raise RuntimeError("`notion_delete_page` Reached the max retries")
