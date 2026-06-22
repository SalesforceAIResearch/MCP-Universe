"""Unit tests for ``mcpuniverse.llm.tito.engine`` engines.

These tests exercise the *public surface* of ``AsyncVLLMEngine`` and
``AsyncSGLangEngine`` without actually loading any model — so they run
fast and do not require a GPU. They verify:

1. Both classes are importable as long as the entrypoint module loads
   (vllm / sglang are imported lazily inside ``init_engine``).
2. Their constructors store a sensible ``*EngineConfig`` dataclass.
3. SGLang's sampling-params normalization correctly maps ``max_tokens`` →
   ``max_new_tokens`` and extracts the ``return_logprobs`` flag (a common
   point where vLLM/SGLang differ).
4. SGLang's ``init_engine`` raises a clear ``ImportError`` when sglang is
   not importable (rather than a confusing AttributeError downstream).
"""

import pytest

from mcpuniverse.llm import (
    AsyncSGLangEngine,
    AsyncVLLMEngine,
    SGLangEngineConfig,
    VLLMEngineConfig,
)
# AsyncVLLMEngine.__init__ hard-requires vllm (raises ImportError if absent),
# unlike AsyncSGLangEngine (lazy at init_engine()). ``_AsyncLLMEngine`` is the
# engine module's own "is vllm importable?" sentinel (None when vllm is missing),
# so this one test skips in CI's core-only env instead of erroring.
from mcpuniverse.llm.tito.engine import _AsyncLLMEngine as _VLLM_ENGINE_CLS


@pytest.mark.skipif(_VLLM_ENGINE_CLS is None, reason="vllm not installed")
def test_async_vllm_engine_stores_config_without_engine_load():
    engine = AsyncVLLMEngine(
        model_path="/tmp/fake-model",
        tensor_parallel_size=2,
        max_model_len=4096,
        gpu_memory_utilization=0.85,
    )
    assert isinstance(engine.config, VLLMEngineConfig)
    assert engine.config.model_path == "/tmp/fake-model"
    assert engine.config.tensor_parallel_size == 2
    assert engine.config.max_model_len == 4096
    assert engine.config.gpu_memory_utilization == 0.85
    # No engine handle yet — init is lazy.
    assert engine.engine is None
    assert engine._initialized is False


def test_async_sglang_engine_stores_config_without_engine_load():
    engine = AsyncSGLangEngine(
        model_path="/tmp/fake-model",
        tensor_parallel_size=4,
        max_model_len=8192,
        gpu_memory_utilization=0.75,
        random_seed=123,
    )
    assert isinstance(engine.config, SGLangEngineConfig)
    assert engine.config.model_path == "/tmp/fake-model"
    assert engine.config.tensor_parallel_size == 4
    assert engine.config.max_model_len == 8192
    assert engine.config.gpu_memory_utilization == 0.75
    assert engine.config.random_seed == 123
    assert engine.engine is None
    assert engine._initialized is False


def test_async_sglang_sampling_params_map_max_tokens_to_max_new_tokens():
    # vLLM-style ``max_tokens`` should be remapped to SGLang's ``max_new_tokens``.
    sp, return_logprob = AsyncSGLangEngine._normalize_sampling_params(
        {"max_tokens": 512, "temperature": 0.7, "top_p": 0.9},
        max_new_default=999,
    )
    assert sp == {"max_new_tokens": 512, "temperature": 0.7, "top_p": 0.9}
    assert return_logprob is False


def test_async_sglang_sampling_params_respects_explicit_max_new_tokens():
    sp, _ = AsyncSGLangEngine._normalize_sampling_params(
        {"max_new_tokens": 128, "max_tokens": 999, "temperature": 0.5},
        max_new_default=999,
    )
    # Explicit max_new_tokens wins; max_tokens is dropped to avoid duplicate keys.
    assert sp["max_new_tokens"] == 128
    assert "max_tokens" not in sp
    assert sp["temperature"] == 0.5


def test_async_sglang_sampling_params_extracts_return_logprobs():
    sp, return_logprob = AsyncSGLangEngine._normalize_sampling_params(
        {"max_tokens": 32, "return_logprobs": True, "temperature": 1.0},
        max_new_default=64,
    )
    assert return_logprob is True
    # return_logprobs must be stripped — SGLang doesn't accept it as a
    # sampling param (it's a separate ``async_generate`` kwarg).
    assert "return_logprobs" not in sp
    assert sp["max_new_tokens"] == 32


def test_async_sglang_sampling_params_extracts_legacy_logprobs_flag():
    # vLLM accepts ``logprobs: int`` to request top-N logprobs; we treat any
    # truthy value the same as ``return_logprobs=True`` for SGLang (which
    # has a separate top_logprobs_num kwarg we don't expose yet).
    sp, return_logprob = AsyncSGLangEngine._normalize_sampling_params(
        {"max_tokens": 16, "logprobs": 1},
        max_new_default=32,
    )
    assert return_logprob is True
    assert "logprobs" not in sp


def test_async_sglang_sampling_params_default_max_new_tokens_when_missing():
    sp, _ = AsyncSGLangEngine._normalize_sampling_params(
        {"temperature": 0.7},
        max_new_default=256,
    )
    assert sp["max_new_tokens"] == 256


def test_async_sglang_sampling_params_handles_none_input():
    sp, return_logprob = AsyncSGLangEngine._normalize_sampling_params(
        {}, max_new_default=42,
    )
    assert sp == {"max_new_tokens": 42}
    assert return_logprob is False


@pytest.mark.asyncio
async def test_async_sglang_init_raises_importerror_when_sglang_missing(
    monkeypatch,
):
    """When sglang is not installed (or fails to import), ``init_engine`` must
    raise a clear ImportError rather than a downstream AttributeError.
    """
    engine = AsyncSGLangEngine(model_path="/tmp/fake")

    # Force the lazy import to fail.
    import importlib

    real_import = importlib.import_module

    def _fail_import(name, *args, **kwargs):
        if name.startswith("sglang"):
            raise ImportError(f"simulated sglang missing for {name}")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(importlib, "import_module", _fail_import)
    # Also poison the direct ``from sglang.srt...`` path used in init_engine.
    import sys
    sys.modules.pop("sglang.srt.entrypoints.engine", None)
    monkeypatch.setitem(sys.modules, "sglang", None)
    monkeypatch.setitem(sys.modules, "sglang.srt", None)
    monkeypatch.setitem(sys.modules, "sglang.srt.entrypoints", None)
    monkeypatch.setitem(sys.modules, "sglang.srt.entrypoints.engine", None)

    with pytest.raises(ImportError, match="sglang is required"):
        await engine.init_engine()
