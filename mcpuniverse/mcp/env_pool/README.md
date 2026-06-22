# Environment Pool (`env_pool`)

Manages a pool of isolated MCP environments. Each environment runs an MCP
Gateway plus one or more MCP servers, and can be acquired by an agent, used,
then released back to the pool (reused or destroyed). Environments are backed by
either **Docker** (dockerd) or **daemon-less Apptainer** — both implement the
same `BaseProvisioner` interface, so the manager / dispatcher / rollout code is
backend-agnostic.

## Core Concepts

| Concept | Description |
|---|---|
| **EnvConfig** | Declares what an environment looks like: which MCP servers to run, Dockerfile + per-task `build_args`, resource limits, optional aux control port, etc. |
| **EnvInfo** | Runtime metadata for a live environment: ID, status, gateway address, assigned agent. |
| **BaseProvisioner** | Abstract interface for creating / destroying / resetting environments. |
| **DockerProvisioner** | Drives Docker containers directly (local or remote dockerd). Supports a shared image registry + disk GC. |
| **ApptainerProvisioner** | Daemon-less backend: a thin HTTP client of a per-pod privileged apptainer worker. No dockerd in the per-task create/run/rm hot path. |
| **EnvPoolManager** | Orchestrates the pool: provision, acquire/release, config-aware reuse, background destroy, health checks, reaping, multi-host load balancing. |
| **image_key** | Deterministic key (Dockerfile content hash + `build_args`) shared by both backends so a built image / staged SIF can be matched to an `EnvConfig`. |

## Provisioner backends

| | Docker | Apptainer |
|---|---|---|
| How envs run | `docker build` + `docker run` via dockerd | `apptainer run --writable-tmpfs` inside one long-lived privileged worker per pod |
| Per-task daemon load | High (every create/run/rm hits dockerd) | None (daemon-less) — best for high-concurrency SWE/R2E |
| Image source | local build, optional shared registry (pull/push) | read-only base SIF staged at `/sifs/<image_key>` |
| Teardown | `docker rm` (slow → background destroyer) | kill process group (cheap → inline on release) |

RL integrations pick the backend with `env_pool.provisioner_backend: docker|apptainer`
(see `mcpuniverse/rl/core/env_pool_runtime.py`).

### Apptainer setup

```bash
# One-time per CPU pod: build + start the privileged worker (mounts the SIF store).
CPU_POD_DOCKER_HOST=tcp://<pod>:2375 BUILD=1 bash scripts/bootstrap_apptainer_worker.sh
```

- The worker control server (`apptainer_worker/server.py`) exposes
  `GET /healthz`, `POST /env/start|stop|reset`, `GET /env/health`.
- Each env binds a unique `gateway_port` on the worker's netns; an optional
  auxiliary internal "control" port can be requested via `EnvConfig.control_port_vars`
  (the gateway reverse-proxies a path prefix to it — see `gateway.py`).
- Base images are staged ahead of time as `/sifs/<image_key>/image.sif`.

## Quick Start (Docker)

```python
from mcpuniverse.mcp.env_pool import (
    EnvPoolManager, DockerProvisioner, EnvConfig,
)

# 1. Configure what each environment should run
config = EnvConfig(servers=["playwright", "weather"])

# 2. Create a provisioner (one per Docker host)
provisioner = DockerProvisioner(config=config, host="localhost")

# 3. Create the pool manager
pool = EnvPoolManager(provisioner, max_pool_size=20, auto_scale=True, min_ready_envs=5)

# 4. Pre-provision some environments
await pool.provision(num_envs=10)

# 5. An agent acquires an environment (matched by EnvConfig identity)
env = await pool.acquire(agent_id="agent-1", config=config)
print(env.gateway_address)  # e.g. http://localhost:9001

# 6. Release back to the pool (cached / destroyed per reuse_policy)
await pool.release(env.env_id)

# 7. Tear everything down
await pool.cleanup()
```

## Multi-Host / Load Balancing

Pass multiple provisioners to spread environments across hosts:

```python
p1 = DockerProvisioner(docker_host="tcp://host-a:2375", host="host-a")
p2 = DockerProvisioner(docker_host="tcp://host-b:2375", host="host-b")

pool = EnvPoolManager(
    provisioner=p1,
    provisioners=[p1, p2],
    scheduling="least-loaded",   # default — picks the node with fewest envs
    # scheduling="round-robin",  # simple cyclic selection
)
pool.get_provisioner_stats()  # per-node env counts
```

## Key Parameters

### `EnvConfig`

| Parameter | Default | Description |
|---|---|---|
| `servers` | `[]` | MCP servers to run inside the environment |
| `dockerfile_path` | `None` | Custom Dockerfile (auto-built / staged if provided) |
| `build_args` | `{}` | Per-task `docker build --build-arg` (e.g. a per-task base image); part of the image identity / key |
| `gateway_port` | `8000` | Gateway port inside the container |
| `gateway_mode` | `"sse"` | `"sse"` or `"stdio"` |
| `cpu_limit` / `memory_limit` | `"2"` / `"4g"` | Resource limits |
| `shm_size` | `None` | `/dev/shm` size (browser workloads) |
| `network` | `"bridge"` | Docker network |
| `volumes` | `[]` | Extra `host:container` mounts |
| `use_dockerfile_cmd` | `False` | Run the image's own CMD/entrypoint instead of the default gateway command |
| `health_check_extra_ports` | `[]` | Extra ports to include in health checks |
| `control_port_vars` | `{}` | Optional aux internal port: `{ENV_VAR: template}` (e.g. `{"X_CTRL_PORT": "{port}"}`); the provisioner allocates a unique port and injects it. Empty = no aux port |
| `env_vars` | `{}` | Extra environment variables |

### `EnvPoolManager`

| Parameter | Default | Description |
|---|---|---|
| `max_pool_size` | `50` | Maximum environments in the pool |
| `min_ready_envs` | `0` | Maintain at least this many ready environments |
| `auto_scale` | `False` | Provision on-demand when no ready env is available |
| `reuse_policy` | `"cache"` | On release: `"cache"` (keep for reuse), `"destroy"` (tear down — SWE/R2E one-shot envs), or `"trimmed_cache"` (bounded cache) |
| `max_ready_envs` / `max_ready_per_key` | `0` | Optional ready-cache quotas (global / per config). `0` = unlimited for `cache` |
| `destroy_concurrency` | `8` | Background destroyer worker count |
| `health_check_interval` | `30.0` | Seconds between health-check rounds |
| `reset_on_release` | `False` | Restart the container when released |
| `acquisition_timeout` | `60.0` | Default `acquire()` timeout (seconds) |
| `scheduling` | `"least-loaded"` | Provisioner selection: `"least-loaded"` or `"round-robin"` |

Acquire is **config-aware**: it hands back a ready env whose `EnvConfig` is
compatible (same `image_key`), provisions a fresh one when none match, and — when
the pool is full — evicts an idle *incompatible* env to make room. This is what
lets per-task-image workloads (e.g. R2E, where every task is a different image)
share one pool without cross-contamination.

## Background Tasks

```python
pool.start_background_tasks()   # health-check + auto-scale
pool.start_destroyer()          # async teardown of released/PENDING_DESTROY envs
pool.start_reaper()             # reclaim abandoned envs + periodic image GC
```

- **Health check** — verifies containers are alive; resets / errors them if not.
- **Auto-scale** — provisions when `ready_envs` drops below `min_ready_envs`.
- **Destroyer** — `release()` of a non-reusable env just enqueues it (keeps the
  trajectory's critical path fast); dedicated workers do the slow `docker rm`
  off-band (apptainer tears down inline since it is cheap).
- **Reaper** — periodically reclaims envs held by crashed/abandoned trajectories,
  and (Docker backend, when a registry is configured) GCs unused images once the
  host disk crosses a threshold (evicted images re-pull from the registry).

## Image registry (Docker backend)

When `DockerProvisioner(registry=...)` is set, images are pulled from the shared
registry before building and pushed after a build, so the same image isn't
rebuilt on every host/run; combined with disk-threshold GC this keeps the
Docker host's local disk from filling with per-task images.

## Pool Statistics

```python
stats = pool.get_stats()
stats.total_envs          # total managed environments
stats.ready_envs          # available for acquisition
stats.in_use_envs         # currently assigned to agents
stats.total_acquisitions  # lifetime acquire count
stats.avg_acquisition_wait_ms  # average acquire() wait time (ms)
stats.avg_usage_duration_s     # average env hold time per agent (s)
```
