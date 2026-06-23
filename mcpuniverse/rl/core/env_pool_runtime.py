"""Shared Docker EnvPool construction for rollout integrations."""
# pylint: disable=too-many-lines

from __future__ import annotations

import asyncio
import json
import os
from typing import Any, Dict, List, Optional

from loguru import logger

from mcpuniverse.mcp.env_pool import EnvConfig, EnvPoolManager
from mcpuniverse.mcp.env_pool.base import EnvStatus
from mcpuniverse.mcp.env_pool.docker import DockerProvisioner


def _safe_get(cfg: Any, key: str, default: Any = None) -> Any:
    """Get ``key`` from a dict / OmegaConf-like config, falling back to
    ``default`` when the key is missing or its value is ``None``.

    YAML ``null`` values are coerced to ``default`` so callers can pass a
    sensible fallback without having to special-case ``None`` everywhere.
    """
    if cfg is None:
        return default
    if hasattr(cfg, "get") and callable(cfg.get):
        value = cfg.get(key, default)
    else:
        value = getattr(cfg, key, default)
    return value if value is not None else default


def _resource_get(cfg: Any, key: str, default: Any = None) -> Any:
    """Read a container-resource / build key from an env-pool config.

    Accepts both shapes the runtime may receive:

    * **flat** (raw dict / OmegaConf) where keys like ``memory_limit`` sit at
      the top level, and
    * **parsed** (``EnvPoolConfig`` dataclass) where ``RolloutConfig.from_dict``
      promotes ``cpu_limit`` / ``memory_limit`` into a nested ``resources``
      sub-config and ``use_dockerfile_cmd`` into ``build``.

    Top-level wins; otherwise we look inside ``resources`` then ``build``. This
    is why a YAML/launch ``memory_limit`` / ``cpu_limit`` override actually
    reaches the container instead of silently falling back to the default (the
    plain ``_safe_get`` only sees the top level, so it returned the default
    for any value the dataclass had nested away).
    """
    value = _safe_get(cfg, key, None)
    if value is not None:
        return value
    for sub in ("resources", "build"):
        sub_cfg = _safe_get(cfg, sub, None)
        if sub_cfg is not None:
            value = _safe_get(sub_cfg, key, None)
            if value is not None:
                return value
    return default


def _resolve_env_servers(env_pool_cfg: Any) -> List[str]:
    """Fixed container server surface for pool reuse, with an env-var fallback.

    Primary source is ``env_pool.env_servers`` in the parsed config. But the
    rollouter is a Ray actor and, empirically, the hydra **list** override does
    not always survive the driver->actor config hand-off (scalar resource
    overrides like ``memory_limit`` do, which is why containers get 12g but only
    per-task servers). The ``MCP_ENV_SERVERS`` env var (comma-separated) is
    propagated to Ray workers via runtime_env exactly like the API keys, so it
    reliably reaches the actor and is used as a fallback. Empty -> per-task
    servers (the unchanged default).
    """
    names = _safe_get(env_pool_cfg, "env_servers", None)
    if hasattr(names, "tolist"):
        names = names.tolist()
    if names:
        return [str(n) for n in names]
    raw = os.environ.get("MCP_ENV_SERVERS", "").strip()
    if raw:
        return [s.strip() for s in raw.split(",") if s.strip()]
    return []


def _resolve_control_port_vars(env_pool_cfg: Any) -> Dict[str, str]:
    """Aux control-port templates ({ENV_VAR: "{port}"}), with an env-var fallback.

    Primary source is ``env_pool.control_port_vars`` in the parsed config. But,
    exactly like ``MCP_ENV_SERVERS`` (see ``_resolve_env_servers``), this nested
    dict does not reliably survive the driver->rollouter Ray config hand-off. If
    it's dropped, the worker is asked for NO aux port, the env's control sidecar
    falls back to its image-default port, and -- because apptainer shares the
    worker's network namespace -- every concurrent env collides on that one port
    (``address already in use`` -> envs die at boot + tool calls time out ->
    reward 0). ``MCP_CONTROL_PORT_VARS`` (a JSON object propagated via
    runtime_env) is the robust fallback. Empty -> no aux port (non-SWE envs).
    """
    raw = _safe_get(env_pool_cfg, "control_port_vars", {}) or {}
    if hasattr(raw, "items"):
        result = {str(k): str(v) for k, v in raw.items()}
        if result:
            return result
    env_raw = os.environ.get("MCP_CONTROL_PORT_VARS", "").strip()
    if env_raw:
        try:
            parsed = json.loads(env_raw)
        except (ValueError, TypeError):
            logger.warning(
                "MCP_CONTROL_PORT_VARS is set but is not valid JSON: {!r}", env_raw,
            )
            return {}
        if isinstance(parsed, dict):
            return {str(k): str(v) for k, v in parsed.items()}
    return {}


def resolve_forward_env_vars(env_pool_cfg: Any) -> Dict[str, str]:
    """Collect host environment variables to forward into MCP containers.

    docker_pool MCP servers run INSIDE a container and read their API keys
    from the container's ``os.environ`` (e.g. serper_search reads
    ``SERPER_API_KEY``, jina_scrape reads ``JINA_API_KEY`` /
    ``SUMMARY_LLM_*``). Nothing inside the container loads the host ``.env``,
    so without forwarding, search/scrape tools fail with "API key not set".

    Two config sources under ``env_pool`` (merged; explicit ``env_vars``
    wins on key collision):

      forward_env_vars: [SERPER_API_KEY, JINA_API_KEY, OPENAI_API_KEY, ...]
          names resolved from the LAUNCH process's os.environ (which has the
          host .env loaded). Missing names are warned, not fatal.
      env_vars: {KEY: "literal-value", ...}
          explicit key/value pairs baked into the container directly.

    These end up as ``docker run -e KEY=VALUE`` via ``EnvConfig.env_vars``
    (see mcp/env_pool/docker.py). Forwarding at container-create time keeps
    secrets out of the image layers (unlike baking .env into the build).
    """
    resolved: Dict[str, str] = {}
    names = _safe_get(env_pool_cfg, "forward_env_vars", []) or []
    if hasattr(names, "tolist"):
        names = names.tolist()

    # Fallback source: values straight from the repo .env. The rollouter is a
    # Ray actor whose os.environ depends on Ray runtime_env propagation; if a
    # key didn't make it through (e.g. a stale worker, or a node whose
    # ``ray start`` didn't inherit the host .env), we still want the container
    # to get its API keys. dotenv_values reads the file without mutating
    # os.environ, so it's a safe last resort. Loaded lazily + cached.
    dotenv_fallback = _load_repo_dotenv()

    for name in names:
        name = str(name)
        value = os.environ.get(name) or dotenv_fallback.get(name)
        if value:
            resolved[name] = value
        else:
            logger.warning(
                "env_pool.forward_env_vars: ${} is not in os.environ nor the "
                "repo .env; the MCP container will not receive it.", name,
            )
    explicit = _safe_get(env_pool_cfg, "env_vars", {}) or {}
    if isinstance(explicit, dict):
        resolved.update({str(k): str(v) for k, v in explicit.items()})
    return resolved


_REPO_DOTENV_CACHE: Dict[str, str] | None = None


def _load_repo_dotenv() -> Dict[str, str]:
    """Read the repo-root .env (key->value) without touching os.environ.

    Cached after first call. Returns {} if python-dotenv or the file is
    missing. Used only as a fallback when an env var the operator asked to
    forward isn't present in the (possibly Ray-propagated) process environ.
    """
    global _REPO_DOTENV_CACHE  # pylint: disable=global-statement
    if _REPO_DOTENV_CACHE is not None:
        return _REPO_DOTENV_CACHE
    values: Dict[str, str] = {}
    try:
        from dotenv import dotenv_values, find_dotenv  # pylint: disable=import-outside-toplevel
        path = find_dotenv(usecwd=True)
        if not path:
            # env_pool_runtime.py is mcpuniverse/rl/core/ -> repo root is 4 up.
            candidate = os.path.join(
                os.path.dirname(os.path.abspath(__file__)),
                "..", "..", "..", ".env",
            )
            path = candidate if os.path.isfile(candidate) else ""
        if path:
            values = {k: v for k, v in dotenv_values(path).items() if v}
    except Exception as exc:  # pylint: disable=broad-exception-caught
        logger.warning("Could not load repo .env fallback for env forwarding: {}", exc)
    _REPO_DOTENV_CACHE = values
    return values


def collect_batch_env_specs(batch: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Group batch instances into prewarm specs.

    Returns a list of ``{"dockerfile_path", "servers", "build_args"}`` dicts, one
    per unique ``(dockerfile_path, build_args)``. Grouping by build_args matters
    for per-task-image envs (each task's base image differs) so the
    prewarm builds the RIGHT image per task instead of one image without the base
    arg (which would fail on ``FROM ${BASE_IMAGE}``). For single-image envs,
    build_args is empty -> one spec per dockerfile, unchanged.
    """
    specs: Dict[str, Dict[str, Any]] = {}
    for instance in batch:
        dockerfile_path = instance.get("dockerfile_path", "")
        if not dockerfile_path:
            continue
        build_args = instance.get("build_args") or {}
        if hasattr(build_args, "items"):
            build_args = {str(k): str(v) for k, v in build_args.items()}
        else:
            build_args = {}
        mcp_servers = instance.get("mcp_servers", [])
        if hasattr(mcp_servers, "tolist"):
            mcp_servers = mcp_servers.tolist()
        server_names = [
            server.get("name") if isinstance(server, dict) else server
            for server in mcp_servers
        ]
        key = dockerfile_path + "|" + json.dumps(build_args, sort_keys=True)
        if key not in specs:
            specs[key] = {
                "dockerfile_path": dockerfile_path,
                "servers": list(server_names),
                "build_args": build_args,
            }
        else:
            existing = set(specs[key]["servers"])
            for server_name in server_names:
                if server_name not in existing:
                    specs[key]["servers"].append(server_name)
                    existing.add(server_name)
    return list(specs.values())


def materialize_env_pool_batch(batch: List[Any]) -> List[Dict[str, Any]]:
    """Convert rollout samples to dicts for env-pool runtime helpers."""
    items: List[Dict[str, Any]] = []
    for sample in batch:
        if hasattr(sample, "to_dict"):
            items.append(sample.to_dict())
        else:
            items.append(dict(sample))
    return items


def build_env_configs_from_specs(
    env_specs: Any,
    env_pool_cfg: Any,
) -> List[EnvConfig]:
    """Build ``EnvConfig`` objects from batch env specs.

    Accepts the new list-of-dicts format from ``collect_batch_env_specs``
    (``[{"dockerfile_path", "servers", "build_args"}]``) and, for backward
    compatibility, the old ``{dockerfile_path: [servers]}`` dict (treated as no
    build_args).
    """
    # Backward-compat: old dict format -> normalize to the list-of-specs format.
    if isinstance(env_specs, dict):
        env_specs = [
            {"dockerfile_path": dp, "servers": sv, "build_args": {}}
            for dp, sv in env_specs.items()
        ]

    configs: List[EnvConfig] = []
    forward_env = resolve_forward_env_vars(env_pool_cfg)
    # See build_env_config_for_trajectory: a configured ``env_servers`` makes
    # every container run the same fixed server surface so the pool can reuse
    # them (matters for stateful envs whose per-task server sets
    # would otherwise defeat reuse). Empty -> per-spec servers (unchanged).
    env_servers = _resolve_env_servers(env_pool_cfg)
    for spec in env_specs:
        server_names = spec.get("servers", [])
        configs.append(EnvConfig(
            servers=list(env_servers) if env_servers else list(server_names),
            dockerfile_path=spec.get("dockerfile_path", ""),
            # str(): hydra may parse cpu_limit as an int (e.g. ``cpu_limit=4``);
            # EnvConfig.cpu_limit is typed str and the docker run cmd / reuse key
            # need strings, so coerce here.
            cpu_limit=str(_resource_get(env_pool_cfg, "cpu_limit", "2")),
            memory_limit=str(_resource_get(env_pool_cfg, "memory_limit", "4g")),
            gateway_mode=_safe_get(env_pool_cfg, "gateway_mode", "sse"),
            network=_safe_get(env_pool_cfg, "network", "bridge"),
            use_dockerfile_cmd=_resource_get(
                env_pool_cfg, "use_dockerfile_cmd", False,
            ),
            env_vars=dict(forward_env),
            build_args={str(k): str(v) for k, v in (spec.get("build_args") or {}).items()},
            control_port_vars=_resolve_control_port_vars(env_pool_cfg),
        ))
    return configs


def build_env_config_for_trajectory(
    server_names: List[str],
    dockerfile_path: str,
    env_pool_cfg: Any,
    build_args: Optional[Dict[str, str]] = None,
) -> EnvConfig:
    """Build one ``EnvConfig`` for trajectory-scoped acquisition.

    ``build_args`` are per-task docker build args (e.g. a per-task ``BASE_IMAGE``,
    the task's prebuilt image) so one Dockerfile can wrap any task's base image;
    they are part of the image identity + reuse key. Empty for stateless / single-
    image envs, so those are unaffected.
    """
    # Container server scope: if ``env_servers`` is configured (e.g. a stateful env's
    # full server surface), every container runs that fixed set so the pool can
    # REUSE them across tasks (per-task server sets would otherwise make each
    # env config unique -> no reuse -> a fresh container per trajectory). The
    # agent still only sees its task's servers (use_sample_servers). Empty
    # default -> per-task servers (the unchanged default).
    env_servers = _resolve_env_servers(env_pool_cfg)
    effective_servers = list(env_servers) if env_servers else (server_names or [])
    return EnvConfig(
        servers=effective_servers,
        dockerfile_path=dockerfile_path,
        # str(): hydra may parse cpu_limit as an int (e.g. ``cpu_limit=4``);
        # EnvConfig.cpu_limit is typed str and the docker run cmd / reuse key
        # need strings, so coerce here.
        cpu_limit=str(_resource_get(env_pool_cfg, "cpu_limit", "2")),
        memory_limit=str(_resource_get(env_pool_cfg, "memory_limit", "4g")),
        gateway_mode=_safe_get(env_pool_cfg, "gateway_mode", "sse"),
        network=_safe_get(env_pool_cfg, "network", "bridge"),
        use_dockerfile_cmd=_resource_get(
            env_pool_cfg, "use_dockerfile_cmd", False,
        ),
        env_vars=resolve_forward_env_vars(env_pool_cfg),
        build_args={str(k): str(v) for k, v in (build_args or {}).items()},
        control_port_vars=_resolve_control_port_vars(env_pool_cfg),
    )


class MCPEnvPoolRuntime:
    """Framework-neutral docker_pool runtime for rollout integrations."""

    def __init__(
        self,
        mcp_config: Any,
        *,
        is_async_mode: bool = False,
        env_pool: EnvPoolManager | None = None,
        env_assignments: Dict[str, str] | None = None,
        owner_loop: asyncio.AbstractEventLoop | None = None,
    ) -> None:
        self.mcp_config = mcp_config
        self.is_async_mode = is_async_mode
        self.env_pool = env_pool
        self.env_assignments = dict(env_assignments or {})
        self.prewarm_future: asyncio.Future | None = None
        # Loop that owns ``EnvPoolManager``'s asyncio primitives. All async
        # operations on the pool (acquire/release/provision/reconcile) MUST
        # run on this loop, otherwise asyncio Locks/Queues bound to it will
        # raise ``RuntimeError: ... attached to a different loop``.
        self._owner_loop: asyncio.AbstractEventLoop | None = owner_loop

    @property
    def env_pool_cfg(self) -> Any:
        """Return the configured env-pool section."""
        return getattr(self.mcp_config, "env_pool", None)

    def enabled(self) -> bool:
        """Return whether docker_pool runtime is enabled."""
        env_pool_cfg = self.env_pool_cfg
        return bool(env_pool_cfg and _safe_get(env_pool_cfg, "enabled", False))

    def collect_batch_env_specs(self, batch: List[Any]) -> List[Dict[str, Any]]:
        """Return ``[{dockerfile_path, servers, build_args}, ...]`` specs for a sample batch."""
        return collect_batch_env_specs(materialize_env_pool_batch(batch))

    def build_env_configs(self, env_specs: List[Dict[str, Any]]) -> List[EnvConfig]:
        """Build env configs for prewarm/reconcile."""
        return build_env_configs_from_specs(env_specs, self.env_pool_cfg or {})

    async def initialize(self, max_parallel: int) -> None:  # pylint: disable=too-many-statements
        """Initialize the Docker env pool manager."""
        env_pool_cfg = self.env_pool_cfg
        if not env_pool_cfg or not self.enabled():
            logger.warning("Env pool not enabled in config, skipping initialization")
            return

        if self.env_pool is not None:
            logger.info("Cleaning up existing env pool before creating new one")
            await self.cleanup()

        # Pool size policy. The pool must ALWAYS be able to hold one full
        # pipeline window: up to ``2 * max_parallel`` trajectories are in flight
        # at once (env stage + run stage) and EACH holds a container until
        # cleanup, so a cap below the window starves acquisition (the continuous
        # driver paces to ``2 * max_parallel`` in flight). A reusable cache
        # (cache / trimmed_cache) may keep up to ``max_ready_envs`` extra idle
        # containers ON TOP of the window. config ``max_pool_size`` only raises
        # the ceiling further (e.g. a big warm cache); it never
        # lowers it below the window. ``destroy`` self-regulates (released envs
        # are destroyed, never cached), so a larger ceiling is harmless - the
        # pool naturally sits at ~in_flight instead of filling up.
        reuse_policy = str(_safe_get(env_pool_cfg, "reuse_policy", "cache") or "cache").lower()
        if reuse_policy not in ("cache", "destroy", "trimmed_cache"):
            logger.warning(
                "Unknown env_pool.reuse_policy={!r}; falling back to 'cache'",
                reuse_policy,
            )
            reuse_policy = "cache"
        configured_pool_size = _safe_get(env_pool_cfg, "max_pool_size", 0)
        cache_headroom = 0 if reuse_policy == "destroy" else max(
            0, int(_safe_get(env_pool_cfg, "max_ready_envs", 0) or 0)
        )
        window_pool_size = 2 * max_parallel + 5
        max_pool_size = max(configured_pool_size, window_pool_size + cache_headroom)

        logger.info("Initializing Docker Env Pool (per-task dockerfile mode)")
        logger.info(f"  Docker host: {_safe_get(env_pool_cfg, 'docker_host')}")
        logger.info(f"  Gateway host: {_safe_get(env_pool_cfg, 'host')}")
        logger.info(
            f"  Max pool size: {max_pool_size} "
            f"(reuse_policy={reuse_policy}, window=2*max_parallel({max_parallel})+5="
            f"{window_pool_size}, cache_headroom={cache_headroom}, "
            f"config={configured_pool_size})"
        )

        docker_hosts = list(_safe_get(env_pool_cfg, "docker_hosts", []) or [])
        if not docker_hosts:
            dh = os.environ.get("CPU_POD_DOCKER_HOST")
            if dh:
                docker_hosts.append({
                    "docker_host": dh,
                    "host": os.environ.get("CPU_POD_HOST", "localhost"),
                })
                for i in range(2, 20):
                    dh_i = os.environ.get(f"CPU_POD_DOCKER_HOST_{i}")
                    if not dh_i:
                        break
                    docker_hosts.append({
                        "docker_host": dh_i,
                        "host": os.environ.get(f"CPU_POD_HOST_{i}", "localhost"),
                    })

        build_cfg = getattr(env_pool_cfg, "build", None)
        build_context = (
            _safe_get(build_cfg, "build_context", "")
            if build_cfg
            else _safe_get(env_pool_cfg, "build_context", "")
        )
        # Env-var fallback (like MCP_ENV_SERVERS): the build sub-config may not
        # survive the driver->rollouter Ray config hand-off, and a wrong/default
        # build_context (the launch cwd) breaks Dockerfile COPY + .dockerignore.
        # MCP_BUILD_CONTEXT (propagated via runtime_env) is the robust fallback.
        if not build_context:
            build_context = os.environ.get("MCP_BUILD_CONTEXT", "") or "."
        auto_build = (
            _safe_get(build_cfg, "auto_build", True)
            if build_cfg
            else _safe_get(env_pool_cfg, "auto_build", True)
        )
        # Optional image registry (persistent library on shared storage). When
        # set, the pool pulls images from it before building and pushes after a
        # build, and can GC the host's local image cache (re-pulling on demand).
        # Env-var fallback mirrors MCP_ENV_SERVERS/MCP_BUILD_CONTEXT (survives the
        # driver->rollouter Ray config hand-off). Empty => unchanged build-only.
        registry = (
            _safe_get(env_pool_cfg, "registry", "")
            or os.environ.get("MCP_ENV_REGISTRY", "")
        )
        # Docker-call hardening (tunable; defaults are sane). A hard per-call
        # timeout + dedicated bounded thread pool keep a slow/504-ing daemon
        # endpoint from wedging the rollout loop; transient gateway errors are
        # retried. ``_cfg_num`` keeps explicit 0 (e.g. retries=0) instead of
        # falling back on a truthiness check.
        def _cfg_num(key: str, default, cast):
            val = _safe_get(env_pool_cfg, key, None)
            try:
                return cast(val) if val is not None else default
            except (TypeError, ValueError):
                return default

        # One knob controls both the destroy thread pool (provisioner) and the
        # number of background destroyer workers (manager), so they stay matched.
        destroy_workers = max(1, _cfg_num("destroy_workers", 8, int))

        common_kwargs = {
            "base_port": _safe_get(env_pool_cfg, "base_port", 9000),
            "startup_timeout": _safe_get(env_pool_cfg, "startup_timeout", 180.0),
            "auto_build": auto_build,
            "build_context": build_context,
            "registry": registry,
            # Total concurrent docker subprocess calls. Kept just above
            # provision_concurrency (8) so fast ops (rm/ps/inspect) aren't
            # starved by a wave of creates, while still keeping the daemon out
            # of the create-burst tail-latency blowup zone (>~12 concurrent).
            "max_docker_workers": _cfg_num("max_docker_workers", 12, int),
            # Dedicated pool for destructive ops (docker rm/stop), isolated from
            # creates so teardown backlog never starves container creation.
            "destroy_workers": destroy_workers,
            "docker_cmd_timeout": _cfg_num("docker_cmd_timeout", 180.0, float),
            "docker_build_timeout": _cfg_num("docker_build_timeout", 1800.0, float),
            "docker_cmd_retries": _cfg_num("docker_cmd_retries", 2, int),
        }

        # Provisioner backend switch: "docker" (default) drives dockerd directly;
        # "apptainer" runs each env daemon-less via a per-pod privileged apptainer
        # worker (no dockerd in the per-task hot path). Both implement
        # BaseProvisioner, so the manager / dispatcher / pipeline are unchanged.
        backend = str(
            _safe_get(env_pool_cfg, "provisioner_backend", "")
            or os.environ.get("MCP_PROVISIONER_BACKEND", "")
            or "docker"
        ).strip().lower()

        if backend == "apptainer":
            from mcpuniverse.mcp.env_pool.apptainer import ApptainerProvisioner  # pylint: disable=import-outside-toplevel
            worker_port = int(_safe_get(env_pool_cfg, "apptainer_worker_port", 0) or 8900)
            gw_base_port = int(_safe_get(env_pool_cfg, "base_port", 9000) or 9000)
            gw_port_range = int(_safe_get(env_pool_cfg, "apptainer_port_range", 0) or 200)
            apptainer_kwargs = {
                "base_port": gw_base_port,
                "port_range": gw_port_range,
                "build_context": build_context,
                "startup_timeout": common_kwargs["startup_timeout"],
            }
            if docker_hosts:
                provisioners = [
                    ApptainerProvisioner(
                        host=hc.get("host", "localhost"),
                        worker_port=worker_port,
                        **apptainer_kwargs,
                    )
                    for hc in docker_hosts
                ]
                for hc in docker_hosts:
                    logger.info("  Added Apptainer worker: {}:{}",
                                hc.get("host"), worker_port)
                provisioner = provisioners[0]
            else:
                provisioner = ApptainerProvisioner(
                    host=_safe_get(env_pool_cfg, "host", "localhost"),
                    worker_port=worker_port,
                    **apptainer_kwargs,
                )
                provisioners = None
            logger.info(
                "Provisioner backend: APPTAINER (daemon-less; worker_port={}, "
                "gw_ports={}-{})",
                worker_port, gw_base_port, gw_base_port + gw_port_range - 1,
            )
        elif docker_hosts:
            provisioners = []
            for host_cfg in docker_hosts:
                provisioner = DockerProvisioner(
                    docker_host=host_cfg.get("docker_host"),
                    host=host_cfg.get("host", "localhost"),
                    **common_kwargs,
                )
                provisioners.append(provisioner)
                logger.info(
                    f"  Added Docker host: {host_cfg.get('docker_host')} "
                    f"(gateway: {host_cfg.get('host')})"
                )
            provisioner = provisioners[0]
        else:
            provisioner = DockerProvisioner(
                docker_host=_safe_get(env_pool_cfg, "docker_host"),
                host=_safe_get(env_pool_cfg, "host"),
                **common_kwargs,
            )
            provisioners = None

        # How long a trajectory waits to acquire a container before giving up.
        # It must never be shorter than a single container's ``startup_timeout``:
        # an acquire that triggers a fresh build + run can legitimately take
        # that long, so a smaller value would time out before the very container
        # it is waiting on becomes ready. When unset, default to
        # ``max(startup_timeout, 300s)`` (300s covers per-task image build/pull
        # churn). An explicit override (config or
        # ``MCP_ENV_ACQUISITION_TIMEOUT``, which survives the driver->rollouter
        # hand-off) is honored but still floored at ``startup_timeout``.
        startup_timeout = common_kwargs["startup_timeout"]
        configured_acq = float(
            _safe_get(env_pool_cfg, "acquisition_timeout", 0)
            or os.environ.get("MCP_ENV_ACQUISITION_TIMEOUT", 0)
            or 0.0
        )
        acquisition_timeout = configured_acq or max(startup_timeout, 300.0)
        if acquisition_timeout < startup_timeout:
            logger.warning(
                "acquisition_timeout ({:.0f}s) < startup_timeout ({:.0f}s); "
                "raising to startup_timeout so acquire can outlast a cold "
                "container build/run.",
                acquisition_timeout, startup_timeout,
            )
            acquisition_timeout = startup_timeout
        # How many containers may be created concurrently. CRITICAL daemon
        # protection: measured per-create latency stays ~0.7s up to ~8 concurrent
        # creates, but EXPLODES (58s+ observed, 180s timeouts) beyond that - a
        # create burst serializes on Docker's port / bridge-IP allocation and the
        # daemon's global container lock, so the tail blows up (this is what
        # wedged/throttled the rollout). Cap concurrent creates at a daemon-safe
        # default of 8; even bounded, 8 creates x ~0.7s ~= 600 creates/min, far
        # above demand. An explicit env_pool.provision_concurrency override wins.
        # Docker serializes on its global container lock beyond ~8 concurrent
        # creates, so cap there. The apptainer backend is daemon-less (no such
        # bottleneck), so it defaults to the full max_parallel.
        _default_prov_conc = max_parallel if backend == "apptainer" else min(max_parallel, 8)
        provision_concurrency = max(
            1,
            int(_safe_get(env_pool_cfg, "provision_concurrency", 0)
                or _default_prov_conc),
        )
        self.env_pool = EnvPoolManager(
            provisioner=provisioner,
            provisioners=provisioners,
            max_pool_size=max_pool_size,
            reset_on_release=_safe_get(env_pool_cfg, "reset_on_release", True),
            acquisition_timeout=acquisition_timeout,
            auto_scale=True,
            provision_concurrency=provision_concurrency,
            destroy_concurrency=destroy_workers,
            reuse_policy=reuse_policy,
            max_ready_envs=int(_safe_get(env_pool_cfg, "max_ready_envs", 0) or 0),
            max_ready_per_key=int(_safe_get(env_pool_cfg, "max_ready_per_key", 0) or 0),
        )
        logger.info(
            "  Concurrency [{}]: provision={} creates, docker_workers={} total, "
            "destroy={} (isolated pool + background workers)",
            backend,
            provision_concurrency,
            common_kwargs["max_docker_workers"],
            destroy_workers,
        )
        logger.info(
            "  Reuse policy: {} (max_ready_envs={}, max_ready_per_key={})",
            reuse_policy,
            getattr(self.env_pool, "max_ready_envs", 0),
            getattr(self.env_pool, "max_ready_per_key", 0),
        )
        # Capture the loop that just constructed the pool. ``EnvPoolManager``
        # creates ``asyncio.Lock`` / ``asyncio.Queue`` lazily on first use; we
        # treat the initialize() loop as the canonical owner so all later
        # operations (acquire, release, provision, reconcile) run there.
        self._owner_loop = asyncio.get_running_loop()
        # Background destruction: teardown runs off the trajectory critical path
        # on a dedicated thread pool, so a slow ``docker rm`` can never starve
        # container creation (the cause of rollout-wide stalls). Plus a reaper
        # to self-heal any env left behind by a failed teardown.
        self.env_pool.start_destroyer()
        self.env_pool.start_reaper()
        logger.info("Env Pool manager created (containers will be provisioned on demand)")

    async def prewarm(self, batch: List[Any], max_parallel: int) -> None:
        """Pre-warm Docker containers before trajectory execution."""
        if self.env_pool is None:
            return
        if getattr(self.env_pool, "reuse_policy", "cache") == "destroy":
            logger.info("Skipping ready-cache prewarm (reuse_policy=destroy)")
            return

        await self.cleanup_stale_containers()
        # Free the Docker host's local image cache before pulling/building this
        # batch's images, so a large task library (per-task images) doesn't fill
        # the (small) local disk. Only acts when a registry is configured + disk
        # is high; evicted images are re-pulled from the registry on demand.
        await self._gc_images_if_needed()

        env_specs = self.collect_batch_env_specs(batch)
        if not env_specs:
            logger.info("No dockerfile_path in batch, skipping pre-warm")
            return

        configs = self.build_env_configs(env_specs)
        # Pre-warm ~2 * max_parallel (one prefetch window: the run stage holds
        # ~max_parallel and the next wave is ~max_parallel), capped by
        # max_pool_size. NOT the whole batch - the continuous pipeline streams
        # waves and cleans as it goes, so a window's worth is enough.
        desired_prewarm = 2 * max_parallel
        total_prewarm = min(desired_prewarm, self.env_pool.max_pool_size)
        per_config = max(1, total_prewarm // len(configs))

        logger.info(
            f"Pre-warming env pool: {total_prewarm} containers "
            f"(desired={desired_prewarm} = 2 x max_parallel({max_parallel}), "
            f"capped by max_pool_size={self.env_pool.max_pool_size}; "
            f"{len(configs)} unique Dockerfiles, {per_config} each)"
        )

        for cfg in configs:
            n = min(per_config, total_prewarm)
            if n <= 0:
                break
            try:
                envs = await self.env_pool.provision(
                    num_envs=n, config=cfg, parallel=True,
                )
                logger.info(
                    f"Pre-warmed {len(envs)} containers for "
                    f"dockerfile={cfg.dockerfile_path}"
                )
                total_prewarm -= len(envs)
            except Exception as exc:  # pylint: disable=broad-exception-caught
                logger.warning(f"Pre-warm failed for {cfg.dockerfile_path}: {exc}")

        stats = getattr(self.env_pool, "_stats", None)
        logger.info(
            "Pre-warm complete. Pool: {} ready, {} total",
            getattr(stats, "ready_envs", "?"),
            getattr(stats, "total_envs", "?"),
        )

    async def cleanup_stale_containers(self) -> None:
        """Remove stale MCP-managed containers from previous training runs."""
        if self.env_pool is None:
            return

        tracked_ids = set(getattr(self.env_pool, "_envs", {}).keys())
        total_removed = 0

        for provisioner in getattr(self.env_pool, "_provisioners", []):
            if not hasattr(provisioner, "docker_host"):
                continue
            try:
                result = await provisioner._run_docker_cmd(  # pylint: disable=protected-access
                    [
                        "ps", "-a", "--filter", "label=mcp.managed=true",
                        "--format", "{{.Names}}\t{{.Status}}",
                    ],
                    check=False,
                )
                if result.returncode != 0 or not result.stdout.strip():
                    continue

                for line in result.stdout.strip().split("\n"):
                    parts = line.split("\t")
                    name = parts[0].strip()
                    if not name.startswith("mcp-env-"):
                        continue
                    env_id = name[len("mcp-env-"):]
                    if env_id in tracked_ids:
                        continue

                    logger.info(
                        "Removing stale container {} from {} (not tracked by pool)",
                        name, provisioner.docker_host or "local",
                    )
                    await provisioner._run_docker_cmd(  # pylint: disable=protected-access
                        ["rm", "-f", name], check=False,
                    )
                    total_removed += 1
            except Exception as exc:  # pylint: disable=broad-exception-caught
                logger.warning(
                    "Failed to cleanup stale containers on {}: {}",
                    getattr(provisioner, "docker_host", "local"), exc,
                )

        if total_removed:
            logger.info("Cleaned up {} stale containers", total_removed)

    async def _gc_images_if_needed(self) -> None:
        """Garbage-collect unused images on each Docker host when disk is high.

        No-op unless a registry is configured (so evicted images can be re-pulled
        on demand). Keeps the host's small local cache to roughly the working set
        even with a large per-task image library.
        """
        if self.env_pool is None:
            return
        for provisioner in getattr(self.env_pool, "_provisioners", []):
            gc = getattr(provisioner, "gc_unused_images", None)
            if gc is None:
                continue
            try:
                await gc()
            except Exception as exc:  # pylint: disable=broad-exception-caught
                logger.warning(
                    "Image GC failed on {}: {}",
                    getattr(provisioner, "docker_host", "local"), exc,
                )

    async def reconcile(self, batch: List[Any], max_parallel: int) -> None:
        """Reconcile pool contents with what the new batch needs."""
        if self.env_pool is None:
            return
        if getattr(self.env_pool, "reuse_policy", "cache") == "destroy":
            logger.info("Skipping ready-cache reconcile (reuse_policy=destroy)")
            return

        env_specs = self.collect_batch_env_specs(batch)
        if not env_specs:
            return

        # collect_batch_env_specs returns a list of spec dicts (one per unique
        # dockerfile/build_args), so gather the needed dockerfile paths from each
        # spec rather than treating the result as a dict.
        needed_dockerfiles = {spec["dockerfile_path"] for spec in env_specs}
        all_envs = self.env_pool.get_all_envs()
        matching = 0
        non_matching_ids: List[str] = []

        for env_info in all_envs:
            if env_info.status == EnvStatus.TERMINATED:
                continue
            if (
                env_info.config
                and env_info.config.dockerfile_path in needed_dockerfiles
            ):
                matching += 1
            elif env_info.status == EnvStatus.READY:
                non_matching_ids.append(env_info.env_id)

        logger.info(
            f"Pool reconciliation: {matching} matching, "
            f"{len(non_matching_ids)} non-matching READY containers"
        )

        # Want ~2 * max_parallel warm containers (one prefetch window), capped by
        # max_pool_size. Not the whole batch - the continuous pipeline streams
        # waves and cleans as it goes.
        want = min(2 * max_parallel, self.env_pool.max_pool_size)
        to_evict = max(0, (matching + len(non_matching_ids)) - want)
        shortfall = max(0, want - matching)
        to_evict = max(to_evict, min(shortfall, len(non_matching_ids)))

        evicted = 0
        for env_id in non_matching_ids[:to_evict]:
            try:
                await self.env_pool.destroy(env_id)
                evicted += 1
            except Exception as exc:  # pylint: disable=broad-exception-caught
                logger.warning(f"Failed to evict {env_id}: {exc}")

        if evicted:
            logger.info(f"Evicted {evicted} non-matching containers")

        need_new = max(0, want - matching)
        if need_new > 0:
            configs = self.build_env_configs(env_specs)
            per_config = max(1, need_new // len(configs))
            remaining = need_new
            for cfg in configs:
                n = min(per_config, remaining)
                if n <= 0:
                    break
                try:
                    envs = await self.env_pool.provision(
                        num_envs=n, config=cfg, parallel=True,
                    )
                    remaining -= len(envs)
                    logger.info(
                        f"Provisioned {len(envs)} containers for "
                        f"dockerfile={cfg.dockerfile_path}"
                    )
                except Exception as exc:  # pylint: disable=broad-exception-caught
                    logger.warning(f"Provision failed for {cfg.dockerfile_path}: {exc}")
        else:
            logger.info(
                f"Pool already has {matching} matching containers, "
                f"no additional provisioning needed"
            )

        stats = getattr(self.env_pool, "_stats", None)
        logger.info(
            "Reconciliation done. Pool: {} ready, {} total",
            getattr(stats, "ready_envs", "?"),
            getattr(stats, "total_envs", "?"),
        )

    async def release_assigned(self) -> None:
        """Release all assigned environments back to the pool."""
        if self.env_pool is None:
            return

        released = 0
        for _, env_id in list(self.env_assignments.items()):
            try:
                await self.env_pool.release(env_id)
                released += 1
            except Exception as exc:  # pylint: disable=broad-exception-caught
                logger.warning(f"Failed to release env {env_id}: {exc}")
        self.env_assignments = {}

        stats = getattr(self.env_pool, "_stats", None)
        logger.info(
            "Released {} environments. Pool: {} ready, {} total",
            released,
            getattr(stats, "ready_envs", "?"),
            getattr(stats, "total_envs", "?"),
        )

    def start_background_prewarm(self, batch: List[Any], max_parallel: int) -> None:
        """Schedule reconcile on the loop that owns the env pool.

        Lookahead: overlaps Docker reconcile/provision for an upcoming batch
        with the CURRENT batch's rollout (hybrid mode: with the gradient update),
        so the next batch starts with warm containers instead of cold-starting.

        Safety invariant: ``EnvPoolManager``'s asyncio primitives (Lock,
        Queue, Task) are bound to ``self._owner_loop`` (captured in
        ``initialize()``). All async pool operations must run on that loop,
        otherwise we hit ``RuntimeError: ... attached to a different loop``.

        This method also guards against overlapping reconciles: if a previous
        background prewarm is still in-flight, this call is a no-op so two
        reconcile coroutines never mutate the same pool concurrently.
        """
        if self.env_pool is None:
            return

        if self._owner_loop is None or self._owner_loop.is_closed():
            logger.warning(
                "Cannot start background prewarm: env-pool owner loop "
                "unavailable (was initialize() called?)"
            )
            return

        if self.prewarm_future is not None and not self.prewarm_future.done():
            logger.info(
                "Previous background prewarm still in-flight; skipping this round"
            )
            return

        self.prewarm_future = asyncio.run_coroutine_threadsafe(
            self.reconcile(batch, max_parallel),
            self._owner_loop,
        )
        logger.info(
            "Background prewarm submitted to env-pool loop (overlaps gradient update)"
        )

    async def await_background_prewarm(self, timeout: float = 300.0) -> None:
        """Wait for the in-flight background prewarm to finish."""
        future = self.prewarm_future
        if future is None or future.done():
            self.prewarm_future = None
            return

        logger.info("Waiting for background prewarm to complete...")
        try:
            await asyncio.wait_for(
                asyncio.wrap_future(future), timeout=timeout,
            )
            logger.info("Background prewarm completed")
        except asyncio.TimeoutError:
            logger.warning(
                f"Background prewarm timed out after {timeout}s, cancelling"
            )
            future.cancel()
        except asyncio.CancelledError:
            logger.warning("Background prewarm cancelled")
            raise
        except Exception as exc:  # pylint: disable=broad-exception-caught
            logger.warning("Background prewarm failed: {}", exc)
        finally:
            self.prewarm_future = None

    async def cleanup(self) -> None:
        """Destroy the entire pool. Called on shutdown only."""
        # Cancel any in-flight background prewarm before tearing the pool down,
        # otherwise reconcile may keep racing against destroy.
        future = self.prewarm_future
        if future is not None and not future.done():
            future.cancel()
            try:
                await asyncio.wait_for(
                    asyncio.wrap_future(future), timeout=5.0,
                )
            except (asyncio.TimeoutError, asyncio.CancelledError):
                pass
            except Exception as exc:  # pylint: disable=broad-exception-caught
                logger.warning("In-flight prewarm cancellation failed: {}", exc)
        self.prewarm_future = None

        if self.env_pool is None:
            return

        logger.info("Cleaning up Docker Env Pool (full destroy)...")
        for _, env_id in list(self.env_assignments.items()):
            try:
                await self.env_pool.release(env_id)
            except Exception as exc:  # pylint: disable=broad-exception-caught
                logger.warning(f"Failed to release env {env_id}: {exc}")
        self.env_assignments = {}

        await self.env_pool.cleanup()
        self.env_pool = None
        self._owner_loop = None
        logger.info("Env Pool cleaned up")

    async def acquire(
        self,
        instance_id: Any,
        traj_id: int,
        dockerfile_path: str,
        server_names: List[str] | None = None,
        build_args: Optional[Dict[str, str]] = None,
    ) -> str:
        """Acquire an environment from the pool for one trajectory."""
        if self.env_pool is None:
            raise RuntimeError("Env pool not initialized")

        traj_key = f"{instance_id}-{traj_id}"
        agent_id = f"agent-{traj_key}"
        config = build_env_config_for_trajectory(
            server_names or [],
            dockerfile_path,
            self.env_pool_cfg or {},
            build_args=build_args,
        )

        env = await self.env_pool.acquire(agent_id=agent_id, config=config)
        self.env_assignments[traj_key] = env.env_id

        logger.debug(
            f"Acquired env {env.env_id} for {traj_key} "
            f"(dockerfile={dockerfile_path}): {env.gateway_address}"
        )
        return env.gateway_address

    async def release(self, instance_id: Any, traj_id: int) -> None:
        """Release a trajectory-scoped environment back to the pool."""
        if self.env_pool is None:
            return

        traj_key = f"{instance_id}-{traj_id}"
        env_id = self.env_assignments.pop(traj_key, None)
        if env_id:
            try:
                await self.env_pool.release(env_id)
                logger.debug(f"Released env {env_id} for {traj_key}")
            except Exception as exc:  # pylint: disable=broad-exception-caught
                logger.warning(f"Failed to release env {env_id} for {traj_key}: {exc}")


__all__ = [
    "MCPEnvPoolRuntime",
    "build_env_config_for_trajectory",
    "build_env_configs_from_specs",
    "collect_batch_env_specs",
    "materialize_env_pool_batch",
    "resolve_forward_env_vars",
]
