"""
MCP Environment Pool Management.

Provides distributed MCP environment management for agent rollout.
Each Env is an isolated container running MCP Gateway + MCP servers.

Usage:
    from mcpuniverse.mcp.env_pool import EnvPoolManager, DockerProvisioner, EnvConfig

    # Create provisioner
    provisioner = DockerProvisioner(
        image="mcp-universe/gateway:latest",
        config=EnvConfig(servers=["playwright", "weather"])
    )

    # Create pool manager
    pool = EnvPoolManager(provisioner, max_pool_size=20)

    # Provision environments
    await pool.provision(num_envs=5)

    # Agent acquires an environment
    env = await pool.acquire(agent_id="agent-1")
    print(f"Gateway: {env.gateway_address}")

    # Agent releases the environment
    await pool.release(env.env_id)

    # Cleanup
    await pool.cleanup()
"""

from .base import (
    ContainerInfo,
    EnvConfig,
    EnvInfo,
    EnvStatus,
    env_config_key,
    env_configs_compatible,
)
from .docker import DockerProvisioner
from .manager import EnvPoolManager

__all__ = [
    # Base types
    "ContainerInfo",
    "EnvConfig",
    "EnvInfo",
    "EnvStatus",
    "env_config_key",
    "env_configs_compatible",
    # Provisioners
    "DockerProvisioner",
    # Manager
    "EnvPoolManager",
]
