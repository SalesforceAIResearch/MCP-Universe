"""Tests for env-var forwarding into docker_pool MCP containers.

``resolve_forward_env_vars`` is what lets deep-research search tools
(serper/jina) running INSIDE a container receive their API keys: the
launch process reads them from the host .env into os.environ, and this
helper forwards the named vars into ``EnvConfig.env_vars`` (which become
``docker run -e KEY=VALUE``).

Covers:
- forward_env_vars resolves names from os.environ
- missing names are skipped (warned, not fatal)
- explicit env_vars dict is merged and wins on collision
- empty/absent config -> empty dict (yfinance / no-key tasks unaffected)
- build_env_config_for_trajectory / build_env_configs_from_specs actually
  populate EnvConfig.env_vars from the config
"""

import pytest

from mcpuniverse.rl.core.env_pool_runtime import (
    resolve_forward_env_vars,
    build_env_config_for_trajectory,
    build_env_configs_from_specs,
)


def test_forward_env_vars_resolves_from_os_environ(monkeypatch):
    monkeypatch.setenv("SERPER_API_KEY", "serper-xyz")
    monkeypatch.setenv("JINA_API_KEY", "jina-abc")
    cfg = {"forward_env_vars": ["SERPER_API_KEY", "JINA_API_KEY"]}
    resolved = resolve_forward_env_vars(cfg)
    assert resolved == {"SERPER_API_KEY": "serper-xyz", "JINA_API_KEY": "jina-abc"}


def test_forward_env_vars_skips_missing(monkeypatch):
    monkeypatch.setenv("SERPER_API_KEY", "serper-xyz")
    monkeypatch.delenv("NOT_SET_KEY", raising=False)
    cfg = {"forward_env_vars": ["SERPER_API_KEY", "NOT_SET_KEY"]}
    resolved = resolve_forward_env_vars(cfg)
    # Missing var is omitted, not crashed on.
    assert resolved == {"SERPER_API_KEY": "serper-xyz"}


def test_explicit_env_vars_merge_and_win(monkeypatch):
    monkeypatch.setenv("SERPER_API_KEY", "from-environ")
    cfg = {
        "forward_env_vars": ["SERPER_API_KEY"],
        # explicit literal wins over the forwarded value on key collision
        "env_vars": {"SERPER_API_KEY": "explicit", "EXTRA": "1"},
    }
    resolved = resolve_forward_env_vars(cfg)
    assert resolved["SERPER_API_KEY"] == "explicit"
    assert resolved["EXTRA"] == "1"


def test_empty_config_yields_empty(monkeypatch):
    # No forward list, no explicit dict -> nothing forwarded (the default for
    # tasks like yfinance that don't need any API keys in the container).
    assert resolve_forward_env_vars({}) == {}
    assert resolve_forward_env_vars(None) == {}


def test_non_string_values_coerced(monkeypatch):
    cfg = {"env_vars": {"PORT": 8000, "FLAG": True}}
    resolved = resolve_forward_env_vars(cfg)
    assert resolved == {"PORT": "8000", "FLAG": "True"}


def test_build_env_config_for_trajectory_populates_env_vars(monkeypatch):
    monkeypatch.setenv("SERPER_API_KEY", "k1")
    cfg = {"forward_env_vars": ["SERPER_API_KEY"], "cpu_limit": "2"}
    ec = build_env_config_for_trajectory(
        server_names=["serper-search"],
        dockerfile_path="/path/Dockerfile.base",
        env_pool_cfg=cfg,
    )
    assert ec.env_vars == {"SERPER_API_KEY": "k1"}
    assert ec.servers == ["serper-search"]
    assert ec.dockerfile_path == "/path/Dockerfile.base"


def test_build_env_configs_from_specs_populates_env_vars(monkeypatch):
    monkeypatch.setenv("JINA_API_KEY", "jk")
    cfg = {"forward_env_vars": ["JINA_API_KEY"]}
    specs = {"/path/Dockerfile.base": ["serper-search", "jina-scrape-llm-summary"]}
    ecs = build_env_configs_from_specs(specs, cfg)
    assert len(ecs) == 1
    assert ecs[0].env_vars == {"JINA_API_KEY": "jk"}
    assert ecs[0].servers == ["serper-search", "jina-scrape-llm-summary"]


def test_yfinance_style_config_unaffected(monkeypatch):
    # A config without forward_env_vars (the existing yfinance shape) must
    # still build a valid EnvConfig with empty env_vars — no regression.
    cfg = {"cpu_limit": "2", "memory_limit": "4g"}
    ec = build_env_config_for_trajectory(
        server_names=["yfinance"],
        dockerfile_path="/path/Dockerfile.base",
        env_pool_cfg=cfg,
    )
    assert ec.env_vars == {}


# --- env_servers (container reuse for stateful envs like toolathlon) ---------

def test_env_servers_overrides_task_servers():
    # When env_servers is configured, EVERY container runs that fixed set so the
    # pool can reuse containers across tasks (the agent still only sees its own
    # task's servers elsewhere). The per-task server_names arg is ignored here.
    cfg = {"env_servers": ["toolathlon-local", "toolathlon-terminal", "toolathlon-canvas"]}
    ec = build_env_config_for_trajectory(
        server_names=["toolathlon-local"],  # a single task's subset
        dockerfile_path="/path/Dockerfile.toolathlon",
        env_pool_cfg=cfg,
    )
    assert ec.servers == ["toolathlon-local", "toolathlon-terminal", "toolathlon-canvas"]


def test_env_servers_empty_uses_task_servers():
    # Empty/absent env_servers (deep research / yfinance) -> per-task servers,
    # i.e. unchanged behaviour.
    ec = build_env_config_for_trajectory(
        server_names=["serper-search", "jina-scrape-llm-summary"],
        dockerfile_path="/path/Dockerfile.base",
        env_pool_cfg={},
    )
    assert ec.servers == ["serper-search", "jina-scrape-llm-summary"]


def test_env_servers_applies_in_batch_specs():
    cfg = {"env_servers": ["toolathlon-local", "toolathlon-terminal"]}
    specs = {"/path/Dockerfile.toolathlon": ["toolathlon-local"]}
    ecs = build_env_configs_from_specs(specs, cfg)
    assert len(ecs) == 1
    assert ecs[0].servers == ["toolathlon-local", "toolathlon-terminal"]


def test_prewarm_groups_by_build_args():
    # R2E: per-task base image (build_args) must produce one prewarm spec per
    # unique image (else the prewarm builds one image without R2E_BASE_IMAGE and
    # `FROM ${R2E_BASE_IMAGE}` fails). Same dockerfile, different build_args -> 2.
    from mcpuniverse.rl.core.env_pool_runtime import collect_batch_env_specs
    batch = [
        {"dockerfile_path": "/D/Dockerfile.r2e", "mcp_servers": [{"name": "r2e-shell"}],
         "build_args": {"R2E_BASE_IMAGE": "img:a"}},
        {"dockerfile_path": "/D/Dockerfile.r2e", "mcp_servers": [{"name": "r2e-shell"}],
         "build_args": {"R2E_BASE_IMAGE": "img:b"}},
        {"dockerfile_path": "/D/Dockerfile.r2e", "mcp_servers": [{"name": "r2e-shell"}],
         "build_args": {"R2E_BASE_IMAGE": "img:a"}},  # dup of the first
    ]
    specs = collect_batch_env_specs(batch)
    assert len(specs) == 2
    imgs = sorted(s["build_args"]["R2E_BASE_IMAGE"] for s in specs)
    assert imgs == ["img:a", "img:b"]
    ecs = build_env_configs_from_specs(specs, {"use_dockerfile_cmd": True})
    assert sorted(ec.build_args["R2E_BASE_IMAGE"] for ec in ecs) == ["img:a", "img:b"]


def test_prewarm_no_build_args_single_spec():
    # Toolathlon / deep research: no build_args -> one spec per dockerfile.
    from mcpuniverse.rl.core.env_pool_runtime import collect_batch_env_specs
    batch = [
        {"dockerfile_path": "/D/Dockerfile.toolathlon", "mcp_servers": [{"name": "toolathlon-local"}]},
        {"dockerfile_path": "/D/Dockerfile.toolathlon", "mcp_servers": [{"name": "toolathlon-terminal"}]},
    ]
    specs = collect_batch_env_specs(batch)
    assert len(specs) == 1
    assert set(specs[0]["servers"]) == {"toolathlon-local", "toolathlon-terminal"}
    assert specs[0]["build_args"] == {}


# --- parsed-dataclass plumbing (regression: nested resources/build) ----------

def test_parsed_env_pool_config_reaches_container():
    """A *parsed* EnvPoolConfig must still feed the container.

    ``RolloutConfig.from_dict`` promotes flat ``cpu_limit`` / ``memory_limit``
    into a nested ``resources`` sub-config and ``use_dockerfile_cmd`` into
    ``build``. The runtime builds EnvConfig with flat reads, so before the
    ``_resource_get`` fix these overrides were silently dropped (container got
    the 4g/2/False defaults). ``env_servers`` is likewise a real field now (it
    used to be discarded entirely during parsing). This is the regression guard.
    """
    from mcpuniverse.rl.core.config import _env_pool_from_dict

    cfg = _env_pool_from_dict({
        "enabled": True,
        "cpu_limit": 4,
        "memory_limit": "12g",
        "use_dockerfile_cmd": True,
        "env_servers": ["toolathlon-local", "toolathlon-terminal"],
    })
    ec = build_env_config_for_trajectory(
        server_names=["toolathlon-local"],
        dockerfile_path="/path/Dockerfile.toolathlon",
        env_pool_cfg=cfg,
    )
    assert ec.servers == ["toolathlon-local", "toolathlon-terminal"]
    assert ec.memory_limit == "12g"
    # cpu_limit comes in as int 4 (hydra) but must reach the container as a
    # string: the docker run cmd is ``' '.join``-ed and asyncio subprocess exec
    # requires str args, so EnvConfig coerces it.
    assert ec.cpu_limit == "4"
    assert isinstance(ec.cpu_limit, str)
    assert ec.use_dockerfile_cmd is True


def test_env_servers_env_var_fallback(monkeypatch):
    # The rollouter reads MCP_ENV_SERVERS from os.environ when the config's
    # env_servers list didn't survive the Ray config hand-off.
    from mcpuniverse.rl.core.env_pool_runtime import _resolve_env_servers
    monkeypatch.setenv("MCP_ENV_SERVERS", "s1,s2,s3")
    assert _resolve_env_servers({}) == ["s1", "s2", "s3"]
    # An explicit config list still wins over the env-var fallback.
    assert _resolve_env_servers({"env_servers": ["a"]}) == ["a"]


def test_env_servers_env_var_empty(monkeypatch):
    from mcpuniverse.rl.core.env_pool_runtime import _resolve_env_servers
    monkeypatch.delenv("MCP_ENV_SERVERS", raising=False)
    assert _resolve_env_servers({}) == []


def test_env_servers_env_var_reaches_envconfig(monkeypatch):
    monkeypatch.setenv("MCP_ENV_SERVERS", "toolathlon-local,toolathlon-terminal")
    ec = build_env_config_for_trajectory(
        server_names=["toolathlon-local"],  # task subset ignored when env-var set
        dockerfile_path="/path/Dockerfile.toolathlon",
        env_pool_cfg={},
    )
    assert ec.servers == ["toolathlon-local", "toolathlon-terminal"]


def test_parsed_env_pool_config_defaults_unaffected():
    # The deep-research shape (no env_servers, default resources) must keep the
    # 4g / per-task-server behaviour after parsing — zero impact.
    from mcpuniverse.rl.core.config import _env_pool_from_dict

    cfg = _env_pool_from_dict({"enabled": True})
    ec = build_env_config_for_trajectory(
        server_names=["serper-search", "jina-scrape-llm-summary"],
        dockerfile_path="/path/Dockerfile.base",
        env_pool_cfg=cfg,
    )
    assert ec.servers == ["serper-search", "jina-scrape-llm-summary"]
    assert ec.memory_limit == "4g"
    assert ec.use_dockerfile_cmd is False
