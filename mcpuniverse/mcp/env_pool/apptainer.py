"""Apptainer-backed environment provisioner.

Runs each task env as an ``apptainer`` container (read-only shared base
+ ephemeral tmpfs overlay) inside a long-lived **privileged worker** container
on a CPU pod -- so dockerd never touches the per-task create/run/rm path that
saturates it under high-concurrency tasks.

This class lives in the rollouter process and is a thin HTTP client of the
per-pod worker control server (`mcpuniverse.mcp.env_pool.apptainer_worker`).
The ``EnvPoolManager`` / dispatcher / continuous pipeline are backend-agnostic:
they only use `BaseProvisioner` + ``EnvInfo.gateway_address``.

Networking model: apptainer shares the worker's network namespace, so each env's
MCP gateway binds a unique port on the worker (published by the worker
container).  ``gateway_address`` therefore points at ``http://{host}:{port}``
where ``host`` is the CPU pod's externally reachable address -- identical to how
`DockerProvisioner` exposes containers, so the rollout client is unchanged.
"""
# Teardown / health-check paths intentionally swallow any backend/HTTP error.
# pylint: disable=broad-exception-caught

from __future__ import annotations

import asyncio
from typing import Dict, List, Optional

import aiohttp
from loguru import logger

from .base import BaseProvisioner, EnvConfig, EnvInfo, EnvStatus
from .image_key import DEFAULT_IMAGE_PREFIX, image_key_for_config


class ApptainerProvisioner(BaseProvisioner):
    """Provision envs via a per-pod apptainer worker control server."""

    # Apptainer teardown is daemon-less and cheap (HTTP -> worker killpg), unlike
    # Docker's slow/daemon-sensitive rm path. Complete teardown directly in
    # EnvPoolManager.release() so a finished trajectory cannot leave an env behind
    # waiting on the generic background destroy queue.
    destroy_inline_on_release = True

    def __init__(
        self,
        host: str = "localhost",
        worker_port: int = 8900,
        base_port: int = 9000,
        port_range: int = 200,
        build_context: str = ".",
        startup_timeout: float = 180.0,
        image_prefix: str = DEFAULT_IMAGE_PREFIX,
        config: Optional[EnvConfig] = None,
        http_timeout: float = 600.0,
        worker_url: Optional[str] = None,
    ):
        """Initialize the Apptainer provisioner.

        Args:
            host: CPU pod host the rollouter uses to reach env gateways AND the
                worker control server (used to build ``gateway_address`` and,
                unless ``worker_url`` is given, the worker URL).
            worker_port: Port of the worker control server on ``host``.
            base_port: First gateway port in the worker's published range.
            port_range: Size of the published gateway-port window (base_port ..
                base_port + port_range - 1).
            build_context: Root used to resolve ``config.dockerfile_path`` when
                computing the image key (must match the Docker build context).
            startup_timeout: Max seconds to wait for an env's gateway to be ready.
            image_prefix: Image-name prefix (only the tag/key is used to locate
                the staged base; kept for parity with DockerProvisioner).
            worker_url: Explicit ``http://host:port`` for the worker control
                server (overrides ``host``/``worker_port`` derivation).
        """
        self.host = host
        self.worker_url = (worker_url or f"http://{host}:{worker_port}").rstrip("/")
        self.base_port = base_port
        self.port_range = max(1, int(port_range))
        self.build_context = build_context
        self.startup_timeout = float(startup_timeout)
        self.image_prefix = image_prefix
        self.default_config = config or EnvConfig()
        self._http_timeout = float(http_timeout)

        self._envs: Dict[str, EnvInfo] = {}
        self._port_map: Dict[str, int] = {}
        self._used_ports: set[int] = set()
        self._port_lock = asyncio.Lock()

    # ------------------------------------------------------------------
    # HTTP helpers
    # ------------------------------------------------------------------
    async def _post(self, path: str, payload: dict, timeout: float) -> dict:
        url = f"{self.worker_url}{path}"
        async with aiohttp.ClientSession() as session:
            async with session.post(
                url, json=payload, timeout=aiohttp.ClientTimeout(total=timeout)
            ) as resp:
                data = await resp.json(content_type=None)
                if resp.status >= 400 or not data.get("ok", False):
                    raise RuntimeError(
                        f"worker {path} failed ({resp.status}): "
                        f"{data.get('error', data)}"
                    )
                return data

    async def _get(self, path: str, timeout: float = 10.0) -> dict:
        url = f"{self.worker_url}{path}"
        async with aiohttp.ClientSession() as session:
            async with session.get(
                url, timeout=aiohttp.ClientTimeout(total=timeout)
            ) as resp:
                return await resp.json(content_type=None)

    # ------------------------------------------------------------------
    # Port allocation (per worker; envs share the worker netns so ports
    # must be unique within this provisioner instance)
    # ------------------------------------------------------------------
    async def _alloc_port(self, env_id: str) -> int:
        async with self._port_lock:
            for port in range(self.base_port, self.base_port + self.port_range):
                if port not in self._used_ports:
                    self._used_ports.add(port)
                    self._port_map[env_id] = port
                    return port
        raise RuntimeError(
            f"No free gateway ports in [{self.base_port}, "
            f"{self.base_port + self.port_range}) on {self.host}"
        )

    async def _free_port(self, env_id: str) -> None:
        async with self._port_lock:
            port = self._port_map.pop(env_id, None)
            if port is not None:
                self._used_ports.discard(port)

    # ------------------------------------------------------------------
    # BaseProvisioner interface
    # ------------------------------------------------------------------
    async def create(self, env_id: str, config: Optional[EnvConfig] = None) -> EnvInfo:
        cfg = config or self.default_config
        image_key = image_key_for_config(cfg, self.build_context)
        port = await self._alloc_port(env_id)
        try:
            await self._post(
                "/env/start",
                {
                    "env_id": env_id,
                    "image_key": image_key,
                    "gateway_port": port,
                    "startup_timeout": self.startup_timeout,
                    "env_vars": dict(cfg.env_vars) if cfg and cfg.env_vars else None,
                    # Optional aux internal port name->template (task-specific names
                    # come from config; worker stays task-agnostic).
                    "control_port_vars": (
                        dict(cfg.control_port_vars)
                        if cfg and getattr(cfg, "control_port_vars", None) else None
                    ),
                },
                timeout=self.startup_timeout + 60.0,
            )
        except Exception:
            await self._free_port(env_id)
            raise

        env_info = EnvInfo(
            env_id=env_id,
            status=EnvStatus.READY,
            gateway_address=f"http://{self.host}:{port}",
            container_id=env_id,
            config=cfg,
        )
        self._envs[env_id] = env_info
        logger.info(
            "Apptainer env {} ready at {} (image_key={}, worker={})",
            env_id, env_info.gateway_address, image_key[:16], self.worker_url,
        )
        return env_info

    async def destroy(self, env_id: str) -> bool:
        try:
            await self._post("/env/stop", {"env_id": env_id},
                             timeout=self._http_timeout)
            ok = True
        except Exception as exc:  # noqa: BLE001 - teardown must not raise
            logger.warning("Apptainer destroy {} failed: {}", env_id, exc)
            ok = False
        finally:
            await self._free_port(env_id)
            self._envs.pop(env_id, None)
        return ok

    async def reset(self, env_id: str) -> bool:
        try:
            await self._post("/env/reset", {"env_id": env_id},
                             timeout=self.startup_timeout + 60.0)
            return True
        except Exception as exc:  # noqa: BLE001
            logger.warning("Apptainer reset {} failed: {}", env_id, exc)
            return False

    async def health_check(self, env_id: str) -> bool:
        try:
            data = await self._get(f"/env/health?env_id={env_id}")
            return bool(data.get("ok"))
        except Exception:  # noqa: BLE001
            return False

    async def get_info(self, env_id: str) -> Optional[EnvInfo]:
        return self._envs.get(env_id)

    async def list_all(self) -> List[EnvInfo]:
        return list(self._envs.values())

    async def cleanup_all(self) -> int:
        count = 0
        for env_id in list(self._envs):
            if await self.destroy(env_id):
                count += 1
        return count
