"""Shared image-key (Dockerfile hash -> tag) computation.

Both the Docker provisioner and the Apptainer provisioner / SIF staging must
agree on the per-config image key so a staged SIF/sandbox base can be matched
to a requested `EnvConfig`.  This mirrors
``DockerProvisioner._image_name_for_config`` *exactly* -- a regression test
(``tests/mcp/env_pool/test_image_key.py``) cross-checks the two so they can
never silently diverge.

The "key" is the bare tag (what follows the ':') and is used as the
``/sifs/<key>`` directory name on the shared SIF store.
"""

import hashlib
import json
import os
from typing import Optional

from .base import EnvConfig

DEFAULT_IMAGE_PREFIX = "mcp-universe/gateway"


def resolve_dockerfile_path(dockerfile_path: str, build_context: str) -> str:
    """Resolve *dockerfile_path* to an absolute path.

    Relative paths are resolved against *build_context* (mirrors
    ``DockerProvisioner._resolve_dockerfile_path``).
    """
    if os.path.isabs(dockerfile_path):
        return dockerfile_path
    return os.path.join(os.path.abspath(build_context), dockerfile_path)


def compute_dockerfile_hash(dockerfile_path: str, build_context: str) -> str:
    """First 16 hex chars of SHA-256 of the Dockerfile *content*.

    Source-code changes do NOT invalidate the key (content-only), matching
    ``DockerProvisioner.compute_dockerfile_hash``.
    """
    abs_path = resolve_dockerfile_path(dockerfile_path, build_context)
    if not os.path.exists(abs_path):
        raise FileNotFoundError(f"Dockerfile not found: {abs_path}")
    with open(abs_path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()[:16]


def image_key_for_config(config: Optional[EnvConfig], build_context: str) -> str:
    """Return the image KEY (the tag portion) for *config*.

    - No ``dockerfile_path`` -> ``"default"``.
    - No ``build_args``      -> 16-hex Dockerfile content hash.
    - With ``build_args``    -> 64-hex ``sha256(dockerfile_hash|build_args_json)``.

    Mirrors ``DockerProvisioner._image_name_for_config`` (minus the prefix).
    """
    if config is None or not config.dockerfile_path:
        return "default"
    dockerfile_hash = compute_dockerfile_hash(config.dockerfile_path, build_context)
    if not config.build_args:
        return dockerfile_hash
    ba = json.dumps(
        {str(k): str(v) for k, v in sorted(config.build_args.items())},
        separators=(",", ":"),
    )
    return hashlib.sha256(f"{dockerfile_hash}|{ba}".encode("utf-8")).hexdigest()


def image_name_for_config(
    config: Optional[EnvConfig],
    build_context: str,
    image_prefix: str = DEFAULT_IMAGE_PREFIX,
) -> str:
    """Return ``{image_prefix}:{image_key_for_config(...)}``."""
    return f"{image_prefix}:{image_key_for_config(config, build_context)}"
