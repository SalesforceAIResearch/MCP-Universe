"""Unit tests for ``AsyncSGLangHTTPEngine`` -- the thin SGLang HTTP client used
by callers (e.g. slime) that own the SGLang server lifecycle elsewhere.

No real server / aiohttp is needed: the class exposes an injectable ``post_fn``
seam (documented "Useful for testing"), so we feed canned SGLang ``/generate``
responses and assert:

* the request payload contract (``input_ids`` + ``return_logprob=True``),
* response normalization (``output_token_logprobs`` -> output_tokens/logprobs,
  finish_reason dict -> ``type``),
* the per-instance ``response_log_probs`` accumulator across multi-turn calls,
* the meta passthrough rules (consumed keys stripped, canonical keys win), and
* that the optional concurrency ``semaphore`` actually wraps the POST.
"""

import asyncio

from mcpuniverse.llm.tito import AsyncSGLangHTTPEngine


def _post_fn(response):
    """An injectable async POST that records calls and returns ``response``."""
    calls = []

    async def fn(url, payload):
        calls.append((url, payload))
        return response

    fn.calls = calls
    return fn


def _sglang_response(*, text="abc", token_logprobs=None, finish_reason=None,
                     extra=None):
    """Build a canned SGLang ``/generate`` JSON response."""
    meta = {}
    if token_logprobs is not None:
        meta["output_token_logprobs"] = token_logprobs
    if finish_reason is not None:
        meta["finish_reason"] = finish_reason
    if extra:
        meta.update(extra)
    return {"text": text, "meta_info": meta}


def test_generate_sends_input_ids_and_parses_logprobs():
    resp = _sglang_response(
        text="hello",
        token_logprobs=[[-0.1, 10, "a"], [-0.2, 20, "b"], [-0.3, 30, "c"]],
        finish_reason={"type": "stop"},
        extra={"prompt_tokens": 5, "completion_tokens": 3},
    )
    fn = _post_fn(resp)
    engine = AsyncSGLangHTTPEngine(url="http://sgl/generate", post_fn=fn)

    text, meta = asyncio.run(engine.generate([1, 2, 3, 4, 5], {"temperature": 0.7}))

    # Request payload contract.
    url, payload = fn.calls[0]
    assert url == "http://sgl/generate"
    assert payload["input_ids"] == [1, 2, 3, 4, 5]
    assert payload["return_logprob"] is True
    assert payload["sampling_params"] == {"temperature": 0.7}

    # Response normalization.
    assert text == "hello"
    assert meta["output_tokens"] == [10, 20, 30]
    assert meta["logprobs"] == [-0.1, -0.2, -0.3]
    assert meta["finish_reason"] == "stop"
    assert meta["prompt_tokens"] == 5
    assert meta["completion_tokens"] == 3


def test_generate_accumulates_response_log_probs_across_calls():
    engine = AsyncSGLangHTTPEngine(
        url="http://sgl/generate",
        post_fn=_post_fn(_sglang_response(
            token_logprobs=[[-1.0, 1, "x"], [-2.0, 2, "y"]],
        )),
    )
    asyncio.run(engine.generate([1], {}))
    asyncio.run(engine.generate([2], {}))
    # The per-instance accumulator must concatenate BOTH turns (multi-turn TITO).
    assert engine.response_log_probs == [-1.0, -2.0, -1.0, -2.0]


def test_reset_clears_accumulated_log_probs():
    engine = AsyncSGLangHTTPEngine(
        url="http://sgl/generate",
        post_fn=_post_fn(_sglang_response(token_logprobs=[[-1.0, 1, "x"]])),
    )
    asyncio.run(engine.generate([1], {}))
    assert engine.response_log_probs == [-1.0]
    engine.reset()
    assert engine.response_log_probs == []


def test_generate_finish_reason_plain_string_passthrough():
    engine = AsyncSGLangHTTPEngine(
        url="http://sgl/generate",
        post_fn=_post_fn(_sglang_response(
            token_logprobs=[[-0.5, 9, "z"]], finish_reason="length",
        )),
    )
    _, meta = asyncio.run(engine.generate([1], {}))
    assert meta["finish_reason"] == "length"


def test_generate_no_logprobs_yields_empty_tokens_and_none_logprobs():
    engine = AsyncSGLangHTTPEngine(
        url="http://sgl/generate",
        post_fn=_post_fn(_sglang_response(text="", token_logprobs=None)),
    )
    text, meta = asyncio.run(engine.generate([1, 2, 3], {}))
    assert text == ""
    assert meta["output_tokens"] == []
    assert meta["logprobs"] is None
    # Defaults derived from inputs when SGLang omits them.
    assert meta["prompt_tokens"] == 3
    assert meta["completion_tokens"] == 0
    assert engine.response_log_probs == []


def test_generate_canonical_keys_win_and_consumed_keys_stripped():
    resp = _sglang_response(
        token_logprobs=[[-0.1, 10, "a"]],
        finish_reason={"type": "stop"},
        extra={"prompt_tokens": 7, "completion_tokens": 1,
               "spec_verify_ct": 5, "e2e_latency": 1.23},
    )
    engine = AsyncSGLangHTTPEngine(url="http://sgl/generate", post_fn=_post_fn(resp))
    _, meta = asyncio.run(engine.generate([1, 2], {}))

    # Consumed raw key must NOT leak through.
    assert "output_token_logprobs" not in meta
    # Canonical normalized values win on overlap.
    assert meta["finish_reason"] == "stop"          # not the {"type": ...} dict
    assert meta["prompt_tokens"] == 7
    assert meta["completion_tokens"] == 1
    # Arbitrary SGLang extras pass through untouched.
    assert meta["spec_verify_ct"] == 5
    assert meta["e2e_latency"] == 1.23


def test_generate_acquires_semaphore_around_post():
    sem = asyncio.Semaphore(1)
    seen = {}

    async def fn(_url, _payload):
        # generate() must have acquired the semaphore before POSTing.
        seen["locked_during_post"] = sem.locked()
        return _sglang_response(token_logprobs=[[-0.1, 1, "a"]])

    engine = AsyncSGLangHTTPEngine(
        url="http://sgl/generate", semaphore=sem, post_fn=fn,
    )
    asyncio.run(engine.generate([1], {}))
    assert seen["locked_during_post"] is True
    assert sem.locked() is False  # released after the call
