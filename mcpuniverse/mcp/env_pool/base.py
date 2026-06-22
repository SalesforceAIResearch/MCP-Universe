"""
Base classes and types for environment provisioners.
"""

import dataclasses
import hashlib
import json
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, NamedTuple, Optional


class EnvStatus(Enum):
    """Environment status."""
    PENDING = "pending"      # Being created
    READY = "ready"          # Ready to use
    IN_USE = "in_use"        # Assigned to an agent
    RESETTING = "resetting"  # Being reset
    ERROR = "error"          # Error state
    PENDING_DESTROY = "pending_destroy"  # Released, queued for background destroy
    TERMINATED = "terminated"  # Destroyed


@dataclass
class EnvConfig:  # pylint: disable=too-many-instance-attributes
    """Configuration for an MCP environment.

    Each task can specify its own Dockerfile.  The system uses the Dockerfile
    hash to decide whether an existing container can be reused: matching hash
    means reset-and-reuse; different hash means build a new image.

    Example:
        config = EnvConfig(
            dockerfile_path="docker/env/Dockerfile.blender",
            servers=["blender", "yfinance"],
        )
    """
    # MCP servers to run in this environment
    servers: List[str] = field(default_factory=list)

    # Dockerfile path (relative to build_context, or absolute).
    # When None, DockerProvisioner uses its default image.
    dockerfile_path: Optional[str] = None

    # Gateway settings
    gateway_port: int = 8000  # Port inside container
    gateway_mode: str = "sse"  # stdio or sse

    # Resource limits (for Docker)
    cpu_limit: str = "2"      # CPU cores
    memory_limit: str = "4g"  # Memory limit
    shm_size: Optional[str] = None  # /dev/shm size (e.g., "2g"). Needed for browser workloads.

    # Network settings
    network: str = "bridge"   # Docker network

    # Additional environment variables
    env_vars: Dict[str, str] = field(default_factory=dict)

    # MCP config file path (inside container)
    mcp_config_path: Optional[str] = None

    # Workspace template (for filesystem isolation)
    workspace_template: Optional[str] = None

    # Extra volume mounts: list of "host_path:container_path" strings.
    # Useful for sharing directories (e.g., blend_files) between host and container.
    volumes: List[str] = field(default_factory=list)

    # If True, use Dockerfile's own CMD/ENTRYPOINT instead of appending gateway command.
    # Needed for environments that require custom startup (e.g., Blender needs Xvfb + addon
    # before gateway). The Dockerfile CMD should start the gateway itself after setup.
    # Gateway port/mode/servers are passed via environment variables (MCP_GATEWAY_PORT, etc.)
    use_dockerfile_cmd: bool = False

    # Extra gateway health-check ports and Docker build args. They are optional
    # per-task env-pool knobs used by RL rollout integrations.
    health_check_extra_ports: List[int] = field(default_factory=list)
    build_args: Dict[str, str] = field(default_factory=dict)

    # Optional auxiliary internal port to allocate for this env, injected into the
    # container under caller-supplied env var name(s) with ``{port}`` formatted in.
    # Generic mechanism: any env needing a second internal port (shared netns)
    # uses it; the NAMES are task-specific and supplied by config, so the
    # provisioner/worker stay task-agnostic. Empty -> no aux port allocated.
    # Example: {"MY_CTRL_PORT": "{port}", "MY_CTRL_URL": "http://localhost:{port}"}
    control_port_vars: Dict[str, str] = field(default_factory=dict)


def _canonical_env_config(config: Optional[EnvConfig]) -> Dict[str, Any]:
    """Return a stable plain dict for EnvConfig identity checks."""
    if config is None:
        return {}
    data = dataclasses.asdict(config)
    data["servers"] = sorted(str(server) for server in data.get("servers", []))
    data["volumes"] = [str(volume) for volume in data.get("volumes", [])]
    data["health_check_extra_ports"] = [
        int(port) for port in data.get("health_check_extra_ports", [])
    ]
    data["env_vars"] = {
        str(key): str(value)
        for key, value in sorted(data.get("env_vars", {}).items())
    }
    data["build_args"] = {
        str(key): str(value)
        for key, value in sorted(data.get("build_args", {}).items())
    }
    return data


def env_config_key(config: Optional[EnvConfig]) -> str:
    """Return a deterministic key for an environment configuration."""
    payload = json.dumps(
        _canonical_env_config(config),
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def env_configs_compatible(
    existing: Optional[EnvConfig],
    requested: Optional[EnvConfig],
) -> bool:
    """Return whether an existing env can satisfy a requested config."""
    if requested is None:
        return True
    if existing is None:
        return env_config_key(requested) == env_config_key(EnvConfig())
    return env_config_key(existing) == env_config_key(requested)


@dataclass
class EnvInfo:
    """Information about a running environment."""
    env_id: str
    status: EnvStatus
    gateway_address: str  # e.g., "http://localhost:9001"

    # Container/process info
    container_id: Optional[str] = None
    process_id: Optional[int] = None

    # Assignment info
    assigned_agent: Optional[str] = None
    assigned_at: Optional[float] = None

    # Timing
    created_at: float = field(default_factory=time.time)

    # Config used
    config: Optional[EnvConfig] = None


class ContainerInfo(NamedTuple):
    """Information about an existing Docker container discovered for reuse."""
    env_id: str
    config: EnvConfig
    status: str  # "running", "exited", "unknown"
    host_port: Optional[int]
    dockerfile_hash: str = ""


class BaseProvisioner(ABC):
    """Abstract base class for environment provisioners."""

    @abstractmethod
    async def create(self, env_id: str, config: EnvConfig) -> EnvInfo:
        """Create a new environment.
        
        Args:
            env_id: Unique environment ID
            config: Environment configuration
            
        Returns:
            EnvInfo with environment details
        """
        raise NotImplementedError

    @abstractmethod
    async def destroy(self, env_id: str) -> bool:
        """Destroy an environment.
        
        Args:
            env_id: Environment ID to destroy
            
        Returns:
            True if successful
        """
        raise NotImplementedError

    @abstractmethod
    async def reset(self, env_id: str) -> bool:
        """Reset an environment to clean state.
        
        Args:
            env_id: Environment ID to reset
            
        Returns:
            True if successful
        """
        raise NotImplementedError

    @abstractmethod
    async def health_check(self, env_id: str) -> bool:
        """Check if an environment is healthy.
        
        Args:
            env_id: Environment ID to check
            
        Returns:
            True if healthy
        """
        raise NotImplementedError

    @abstractmethod
    async def get_info(self, env_id: str) -> Optional[EnvInfo]:
        """Get environment info.
        
        Args:
            env_id: Environment ID
            
        Returns:
            EnvInfo or None if not found
        """
        raise NotImplementedError

    async def list_all(self) -> List[EnvInfo]:
        """List all managed environments."""
        raise NotImplementedError

    async def cleanup_all(self) -> int:
        """Cleanup all managed environments."""
        raise NotImplementedError
