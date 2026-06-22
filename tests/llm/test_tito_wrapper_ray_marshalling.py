"""Regression tests for ``TITOLLMWrapper._call_ray`` payload marshalling.

This file pins down the wire format we send to veRL Ray actors, regardless
of the declared ``backend`` hint. It exists because of a real, hours-long
silent training failure on 2026-05-28:

veRL's ``SGLangHttpServer.generate(prompt_ids: torch.Tensor)`` type hint
*looks* like it wants a tensor, but the underlying SGLang
``GenerateReqInput._determine_batch_size`` actually checks
``isinstance(input_ids[0], int)`` to discriminate single vs batch. Passing
a ``torch.Tensor`` makes ``input_ids[0]`` a 0-d Tensor (not an int), so
SGLang misroutes the request to the batch path, then ``_expand_inputs``
rejects it with ``"input_ids should be a list of lists for batch
processing."``. The exception is silently caught by HarmonyAgent's
``_execute()``, which keeps looping with a default tool, accumulating
~21k tool-result tokens with ``trainable_tokens=0`` per trajectory until
the trainer downstream crashes on
``torch.max(empty_tensor)`` in ``compute_data_metrics``.

The correct contract — verified against SGLang ``io_struct.py`` —— is
**always pass ``list[int]``**, for BOTH vLLM and SGLang Ray actors.
"""

import asyncio
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from mcpuniverse.llm.tito import TITOLLMWrapper


class _FakeTokenizer:
    eos_token_id = 0

    def encode(self, text, add_special_tokens=False):
        return [10 + i for i, _ in enumerate(text.split() or ["x"])]

    def decode(self, ids, skip_special_tokens=False):
        return " ".join(str(int(i)) for i in ids)


class _FakeTokenOutput:
    """Stand-in for ``verl.workers.rollout.replica.TokenOutput`` Pydantic."""

    def __init__(self, token_ids=None, log_probs=None):
        self.token_ids = token_ids or [100, 200, 300]
        self.log_probs = log_probs


def _make_wrapper(backend: str) -> tuple[TITOLLMWrapper, MagicMock]:
    """Build a TITOLLMWrapper with a mocked Ray-actor engine.

    The engine handle's ``generate.remote`` returns a deterministic
    ``ObjectRef``-like sentinel that ``asyncio.to_thread(ray.get, ...)``
    can unblock with a ``_FakeTokenOutput``.
    """
    # Engine is a plain MagicMock so ``hasattr(engine, "generate")`` is True
    # AND ``asyncio.iscoroutinefunction(engine.generate)`` is False — that's
    # the condition for the wrapper to pick the Ray-actor path (see
    # ``TITOLLMWrapper.__init__`` ``_is_local`` detection).
    engine = MagicMock()
    engine.generate = MagicMock()  # non-coroutine — forces Ray path
    object_ref = object()  # sentinel
    engine.generate.remote = MagicMock(return_value=object_ref)

    wrapper = TITOLLMWrapper(
        engine=engine,
        tokenizer=_FakeTokenizer(),
        sampling_params={"temperature": 0.7, "max_tokens": 64},
        backend=backend,
    )
    return wrapper, engine


@pytest.mark.parametrize("backend", ["vllm", "sglang"])
def test_call_ray_always_sends_list_int_not_tensor(backend, monkeypatch):
    """``_call_ray`` MUST send ``prompt_ids`` as ``list[int]``, never
    a ``torch.Tensor``, regardless of the declared backend. This was the
    silent SGLang failure of 2026-05-28.
    """
    wrapper, engine = _make_wrapper(backend)

    # Stub ``ray.get`` so it returns a TokenOutput-like result.
    fake_result = _FakeTokenOutput(token_ids=[100, 200, 300])
    monkeypatch.setattr(
        "mcpuniverse.llm.tito.wrapper.ray.get", lambda ref: fake_result,
    )

    async def _drive():
        return await wrapper._call_ray(
            token_ids=[1, 2, 3, 4, 5],
            sampling_params={"temperature": 0.5, "max_tokens": 32},
            request_id="req-1",
        )

    asyncio.run(_drive())

    # Inspect the exact payload that landed on .generate.remote(...)
    engine.generate.remote.assert_called_once()
    call_kwargs = engine.generate.remote.call_args.kwargs
    payload = call_kwargs["prompt_ids"]

    assert isinstance(payload, list), (
        f"backend={backend}: prompt_ids MUST be list[int], got {type(payload)!r}"
    )
    assert all(isinstance(x, int) for x in payload), (
        f"backend={backend}: prompt_ids elements MUST all be int, got {payload!r}"
    )
    assert payload == [1, 2, 3, 4, 5]


@pytest.mark.parametrize("backend", ["vllm", "sglang"])
def test_call_ray_strips_max_tokens_and_max_new_tokens(backend, monkeypatch):
    """``_call_ray`` should strip both ``max_tokens`` and ``max_new_tokens``
    from sampling_params before forwarding — veRL sets these server-side
    based on the rollout config to avoid mid-trajectory context overflow.
    """
    wrapper, engine = _make_wrapper(backend)
    monkeypatch.setattr(
        "mcpuniverse.llm.tito.wrapper.ray.get",
        lambda ref: _FakeTokenOutput(),
    )

    asyncio.run(
        wrapper._call_ray(
            token_ids=[1, 2, 3],
            sampling_params={
                "temperature": 0.5,
                "max_tokens": 128,
                "max_new_tokens": 256,
            },
            request_id="req-2",
        )
    )
    sp = engine.generate.remote.call_args.kwargs["sampling_params"]
    assert "max_tokens" not in sp
    assert "max_new_tokens" not in sp
    assert sp["temperature"] == 0.5


def test_call_ray_token_ids_iterable_other_than_list_is_normalized(monkeypatch):
    """Accept any int-iterable (tuple, range, etc.) and normalize to list,
    so we never accidentally forward a non-list type that SGLang would
    misroute (the bug being defended against).
    """
    wrapper, engine = _make_wrapper(backend="sglang")
    monkeypatch.setattr(
        "mcpuniverse.llm.tito.wrapper.ray.get",
        lambda ref: _FakeTokenOutput(),
    )

    asyncio.run(
        wrapper._call_ray(
            token_ids=(1, 2, 3, 4),  # tuple — not a list
            sampling_params={"temperature": 0.5},
            request_id="req-3",
        )
    )
    payload = engine.generate.remote.call_args.kwargs["prompt_ids"]
    assert isinstance(payload, list)
    assert payload == [1, 2, 3, 4]


def test_call_ray_handles_token_output_result(monkeypatch):
    """Pydantic-model ``TokenOutput`` result (verl) should be unwrapped
    into ``(decoded_text, list_of_token_ids)`` so the caller can
    ``append_response_tokens(...)``.
    """
    wrapper, engine = _make_wrapper(backend="sglang")
    monkeypatch.setattr(
        "mcpuniverse.llm.tito.wrapper.ray.get",
        lambda ref: _FakeTokenOutput(token_ids=[55, 66, 77]),
    )

    # _call_ray returns the 4-tuple (text, tokens, logprobs, routed_experts);
    # _FakeTokenOutput carries neither log_probs nor routed_experts -> both None.
    text, tokens, logprobs, routed = asyncio.run(
        wrapper._call_ray(
            token_ids=[1],
            sampling_params={"temperature": 0.1},
            request_id="req-4",
        )
    )
    assert tokens == [55, 66, 77]
    assert logprobs is None
    assert routed is None
    # decode is deterministic in _FakeTokenizer
    assert text == "55 66 77"
