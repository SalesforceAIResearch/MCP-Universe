"""
PoC test for CWE-94: Arbitrary code execution via sandbox server with no authentication.

The sandbox_container_server.py exposes an HTTP endpoint /execute on 0.0.0.0:8080
with NO authentication. Any network-reachable client can POST arbitrary Python code
for execution. This test verifies that:

1. BEFORE fix: Requests without valid API key are accepted (vulnerability).
2. AFTER fix: Requests without valid API key are rejected with 401/403.
"""
import os
import sys

import pytest

WORKTREE = os.environ.get(
    "WORKTREE",
    "/Users/sebastion/projects/audits/SalesforceAIResearch-MCP-Universe-worktrees/cwe94-sandbox-container-se-code-0389"
)
SHARED_CLONE = os.environ.get(
    "SHARED_CLONE",
    "/Users/sebastion/projects/audits/SalesforceAIResearch-MCP-Universe"
)

# Try worktree first, then shared clone
for base in [WORKTREE, SHARED_CLONE]:
    sandbox_dir = os.path.join(base, "docker", "python_code_sandbox")
    if os.path.isdir(sandbox_dir):
        sys.path.insert(0, os.path.join(base, "docker"))
        break


import python_code_sandbox.sandbox_container_server as sandbox_mod
from python_code_sandbox.sandbox_container_server import create_app


@pytest.fixture
def app():
    """Create the aiohttp app for testing."""
    return create_app()


@pytest.mark.asyncio
async def test_execute_without_api_key_is_rejected(aiohttp_client, app):
    """
    Requests to /execute WITHOUT a valid API key should be rejected.

    Before fix: returns 200 (vulnerability - arbitrary code execution).
    After fix: returns 401 (unauthorized).
    """
    client = await aiohttp_client(app)

    resp = await client.post(
        "/execute",
        json={"code": "print('pwned')", "timeout": 5}
    )

    # After the fix, this must be 401 or 403
    assert resp.status in (401, 403), (
        f"Expected 401/403 for unauthenticated request, got {resp.status}. "
        "The /execute endpoint is accessible without authentication!"
    )


@pytest.mark.asyncio
async def test_execute_with_wrong_api_key_is_rejected(aiohttp_client, app):
    """
    Requests to /execute with an INVALID API key should be rejected.
    """
    client = await aiohttp_client(app)

    resp = await client.post(
        "/execute",
        json={"code": "print('pwned')", "timeout": 5},
        headers={"Authorization": "Bearer wrong-key-12345"}
    )

    assert resp.status in (401, 403), (
        f"Expected 401/403 for bad API key, got {resp.status}. "
        "The /execute endpoint accepts invalid credentials!"
    )


@pytest.mark.asyncio
async def test_execute_with_valid_api_key_is_accepted(aiohttp_client, monkeypatch):
    """
    Requests to /execute WITH a valid API key should be accepted (status 200).
    """
    test_key = "test-sandbox-secret-key-abc123"
    # Patch the module-level constant so the middleware sees it
    monkeypatch.setattr(sandbox_mod, "SANDBOX_API_KEY", test_key)

    new_app = create_app()
    client = await aiohttp_client(new_app)

    resp = await client.post(
        "/execute",
        json={"code": "print('hello')", "timeout": 5},
        headers={"Authorization": f"Bearer {test_key}"}
    )

    # Should be accepted (200), not rejected
    assert resp.status == 200, (
        f"Expected 200 for valid API key, got {resp.status}"
    )


@pytest.mark.asyncio
async def test_health_endpoint_requires_no_auth(aiohttp_client, app):
    """
    The /health endpoint should remain accessible without authentication.
    """
    client = await aiohttp_client(app)

    resp = await client.get("/health")
    assert resp.status == 200, (
        f"Expected 200 for health check, got {resp.status}"
    )
