"""image_key must stay byte-identical to DockerProvisioner's tag derivation.

If these drift, a staged SIF/sandbox base would never match the key the
ApptainerProvisioner computes for the same EnvConfig, and every env would fail
to provision -- so this cross-check is load-bearing.
"""

import os
import tempfile

from mcpuniverse.mcp.env_pool.base import EnvConfig
from mcpuniverse.mcp.env_pool.docker import DockerProvisioner
from mcpuniverse.mcp.env_pool.image_key import (
    compute_dockerfile_hash,
    image_key_for_config,
)


def _ctx(content: str = "FROM busybox\nRUN echo hi\n") -> str:
    d = tempfile.mkdtemp()
    with open(os.path.join(d, "Dockerfile"), "w", encoding="utf-8") as f:
        f.write(content)
    return d


def _docker_tag(cfg: EnvConfig, ctx: str) -> str:
    dp = DockerProvisioner(build_context=ctx, docker_host="tcp://fake:2375")
    return dp._image_name_for_config(cfg).split(":", 1)[1]


def test_key_matches_docker_no_build_args():
    ctx = _ctx()
    cfg = EnvConfig(dockerfile_path="Dockerfile")
    assert image_key_for_config(cfg, ctx) == _docker_tag(cfg, ctx)


def test_key_matches_docker_with_build_args():
    ctx = _ctx()
    cfg = EnvConfig(
        dockerfile_path="Dockerfile",
        build_args={"R2E_BASE_IMAGE": "namanjain12/aiohttp_final:abc", "Z": "1"},
    )
    key = image_key_for_config(cfg, ctx)
    assert key == _docker_tag(cfg, ctx)
    # build_args -> full 64-hex sha256 (not the 16-hex content hash).
    assert len(key) == 64


def test_key_default_when_no_dockerfile():
    assert image_key_for_config(EnvConfig(), ".") == "default"
    assert image_key_for_config(None, ".") == "default"


def test_compute_hash_is_content_only_and_16_hex():
    ctx = _ctx("FROM busybox\n")
    h1 = compute_dockerfile_hash("Dockerfile", ctx)
    h2 = compute_dockerfile_hash("Dockerfile", ctx)
    assert h1 == h2 and len(h1) == 16
    # Different content -> different hash.
    ctx2 = _ctx("FROM ubuntu\n")
    assert compute_dockerfile_hash("Dockerfile", ctx2) != h1


def test_absolute_dockerfile_path():
    ctx = _ctx()
    abs_df = os.path.join(ctx, "Dockerfile")
    cfg = EnvConfig(dockerfile_path=abs_df)
    assert image_key_for_config(cfg, "/nonexistent") == _docker_tag(cfg, "/nonexistent")
