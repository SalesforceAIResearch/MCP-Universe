"""
Direct vLLM / SGLang Engine integration (no HTTP serve).

This module provides direct access to vLLM's ``AsyncLLMEngine`` and SGLang's
``Engine`` for high-performance inference without HTTP overhead.

Two backends, same interface:
- `AsyncVLLMEngine` — wraps ``vllm.AsyncLLMEngine``
- `AsyncSGLangEngine` — wraps ``sglang.srt.entrypoints.engine.Engine``

Both expose the same async ``generate(prompt_ids, sampling_params, request_id)
-> (text, meta_info)`` contract that ``TITOLLMWrapper`` (and the veRL trainers
that delegate to it) consume, so callers can swap backends without code
changes other than picking the right class.

Usage::

    from mcpuniverse.llm import AsyncVLLMEngine  # or AsyncSGLangEngine

    engine = AsyncVLLMEngine(model_path="...", tensor_parallel_size=1)
    await engine.init_engine()
    response, meta = await engine.generate(
        prompt_ids=[101, 2023, 2003, ...],
        sampling_params={"temperature": 0.7, "max_tokens": 512},
    )
    print(response)              # Generated text
    print(meta["output_tokens"]) # Token IDs
    print(meta["finish_reason"]) # stop, length, etc.

Note: veRL training (hybrid / fully_async) does NOT use these classes
directly — it goes through veRL's own ``vLLMReplica`` / ``SGLangReplica``
Ray actors. These are only consumed by the standalone ``RolloutEngine``
and example notebooks.
"""

from typing import Any, Dict, List, Optional, Tuple
from dataclasses import dataclass, field
import asyncio
import uuid

from loguru import logger

try:
    import ray
except ImportError:
    ray = None

try:
    from vllm import AsyncLLMEngine as _AsyncLLMEngine, SamplingParams
    from vllm.engine.arg_utils import AsyncEngineArgs
    from vllm.inputs import TokensPrompt
except ImportError:
    _AsyncLLMEngine = None
    SamplingParams = None
    AsyncEngineArgs = None
    TokensPrompt = None

# SGLang is loaded lazily inside AsyncSGLangEngine.init_engine() — its
# top-level import has heavy CUDA-side initialization (and currently has
# torch / sgl_kernel version sensitivity), so we don't want to pay the
# cost (or risk an ImportError) at module-import time for users who only
# need vLLM.


@dataclass
class VLLMEngineConfig:
    """Configuration for vLLM engine."""
    model_path: str
    tensor_parallel_size: int = 1
    dtype: str = "auto"
    trust_remote_code: bool = True
    max_model_len: Optional[int] = None
    gpu_memory_utilization: float = 0.9
    enforce_eager: bool = False
    seed: int = 42
    # Additional vLLM engine args
    engine_args: Dict[str, Any] = field(default_factory=dict)


class AsyncVLLMEngine:
    """
    Direct vLLM AsyncLLMEngine wrapper (no HTTP serve).
    
    This provides:
    - Direct generate() with token IDs
    - Output token IDs and logprobs
    - No HTTP overhead
    - Compatible with VERL's distributed training
    
    Similar to SkyRL-Agent's SkyAgentAsyncvLLMServer.
    """

    def __init__(
        self,
        model_path: str,
        tensor_parallel_size: int = 1,
        dtype: str = "auto",
        trust_remote_code: bool = True,
        max_model_len: Optional[int] = None,
        gpu_memory_utilization: float = 0.9,
        **engine_args
    ):
        """
        Initialize the vLLM engine wrapper.

        Args:
            model_path: Path to the model (HuggingFace model ID or local path)
            tensor_parallel_size: Number of GPUs for tensor parallelism
            dtype: Data type for model weights
            trust_remote_code: Whether to trust remote code
            max_model_len: Maximum model context length
            gpu_memory_utilization: GPU memory utilization ratio
            **engine_args: Additional vLLM engine arguments
        """
        if _AsyncLLMEngine is None:
            raise ImportError(
                "vllm is required for AsyncVLLMEngine. "
                "Install with: pip install mcpuniverse[vllm]"
            )
        self.config = VLLMEngineConfig(
            model_path=model_path,
            tensor_parallel_size=tensor_parallel_size,
            dtype=dtype,
            trust_remote_code=trust_remote_code,
            max_model_len=max_model_len,
            gpu_memory_utilization=gpu_memory_utilization,
            engine_args=engine_args
        )

        self.engine = None
        self.tokenizer = None
        self.max_model_len = max_model_len
        self._initialized = False

    async def init_engine(self):
        """Initialize the vLLM AsyncLLMEngine."""
        if self._initialized:
            return

        engine_args = AsyncEngineArgs(
            model=self.config.model_path,
            tensor_parallel_size=self.config.tensor_parallel_size,
            dtype=self.config.dtype,
            trust_remote_code=self.config.trust_remote_code,
            max_model_len=self.config.max_model_len,
            gpu_memory_utilization=self.config.gpu_memory_utilization,
            enforce_eager=self.config.enforce_eager,
            seed=self.config.seed,
            **self.config.engine_args
        )

        self.engine = _AsyncLLMEngine.from_engine_args(engine_args)

        # Get max model length from engine if not specified
        if self.max_model_len is None:
            model_config = await self.engine.get_model_config()
            self.max_model_len = model_config.max_model_len

        self._initialized = True
        logger.info(f"[AsyncVLLMEngine] Initialized with max_model_len={self.max_model_len}")

    async def generate(
        self,
        prompt_ids: List[int],
        sampling_params: Dict[str, Any],
        request_id: Optional[str] = None
    ) -> Tuple[str, Dict[str, Any]]:
        """
        Generate text from token IDs.
        
        Args:
            prompt_ids: Input token IDs
            sampling_params: Sampling parameters dict
            request_id: Optional request ID for tracking
        
        Returns:
            Tuple of (response_text, meta_info)
            meta_info contains:
            - output_tokens: Generated token IDs
            - finish_reason: Why generation stopped
            - logprobs: Token log probabilities (if requested)
        """
        if not self._initialized:
            await self.init_engine()

        # Prepare sampling params
        sp = dict(sampling_params) if sampling_params else {}

        # Handle max_tokens
        if "max_tokens" not in sp or sp["max_tokens"] is None:
            sp["max_tokens"] = self.max_model_len - len(prompt_ids)
        else:
            sp["max_tokens"] = int(sp["max_tokens"])

        # Check for logprobs request
        return_logprobs = sp.pop("return_logprobs", False)
        if return_logprobs:
            sp["logprobs"] = sp.get("logprobs", 1)

        # Create vLLM SamplingParams
        vllm_params = SamplingParams(**sp)

        # Create prompt from token IDs
        prompt = TokensPrompt(prompt_token_ids=prompt_ids)

        # Generate request ID if not provided
        if request_id is None:
            request_id = str(uuid.uuid4())

        # Generate
        generator = self.engine.generate(
            prompt=prompt,
            sampling_params=vllm_params,
            request_id=request_id
        )

        # Get final response
        final_output = None
        async for output in generator:
            final_output = output

        assert final_output is not None, "No output from vLLM engine"

        # Extract results
        output_obj = final_output.outputs[0]
        response_text = output_obj.text
        output_tokens = list(output_obj.token_ids)
        finish_reason = output_obj.finish_reason

        # Extract logprobs if available
        logprobs = None
        if output_obj.logprobs:
            logprobs = [
                lp.logprob if lp else 0.0
                for lp in output_obj.logprobs
            ]

        meta_info = {
            "output_tokens": output_tokens,
            "finish_reason": finish_reason,
            "logprobs": logprobs,
            "prompt_tokens": len(prompt_ids),
            "completion_tokens": len(output_tokens),
        }

        return response_text, meta_info

    async def generate_batch(
        self,
        prompts: List[List[int]],
        sampling_params: Dict[str, Any],
        request_ids: Optional[List[str]] = None
    ) -> List[Tuple[str, Dict[str, Any]]]:
        """
        Generate for multiple prompts concurrently.
        
        Args:
            prompts: List of token ID sequences
            sampling_params: Shared sampling parameters
            request_ids: Optional list of request IDs
        
        Returns:
            List of (response_text, meta_info) tuples
        """
        if request_ids is None:
            request_ids = [str(uuid.uuid4()) for _ in prompts]

        tasks = [
            self.generate(prompt_ids, sampling_params, request_id)
            for prompt_ids, request_id in zip(prompts, request_ids)
        ]

        return await asyncio.gather(*tasks)

    async def get_tokenizer(self):
        """Get the tokenizer from the engine."""
        if not self._initialized:
            raise RuntimeError("Engine not initialized. Call init_engine() first.")
        result = self.engine.get_tokenizer()
        if asyncio.iscoroutine(result):
            return await result
        return result

    async def shutdown(self):
        """Shutdown the engine."""
        if self.engine:
            # vLLM doesn't have explicit shutdown, but we can mark as uninitialized
            self._initialized = False
            self.engine = None


class AsyncVLLMBackend:
    """
    Backend wrapper for AsyncVLLMEngine.
    
    Provides a consistent interface compatible with SkyRL-Agent's AsyncInferBackend.
    """

    def __init__(
        self,
        engine: AsyncVLLMEngine,
        tokenizer: Any = None
    ):
        """
        Initialize the backend.
        
        Args:
            engine: AsyncVLLMEngine instance
            tokenizer: Optional tokenizer (will use engine's tokenizer if not provided)
        """
        self.engine = engine
        self._tokenizer = tokenizer

    @property
    def tokenizer(self):
        """Return the tokenizer, fetching from engine if needed."""
        if self._tokenizer is None:
            self._tokenizer = self.engine.get_tokenizer()
        return self._tokenizer

    async def async_generate_ids(
        self,
        input_ids: List[int],
        sampling_params: Dict[str, Any],
        request_id: str,
        **_kwargs  # Unused, for compatibility
    ) -> Tuple[str, Dict[str, Any]]:
        """
        Generate from token IDs.
        
        Compatible with SkyRL-Agent's AsyncInferBackend interface.
        """
        return await self.engine.generate(
            prompt_ids=input_ids,
            sampling_params=sampling_params,
            request_id=request_id
        )

    async def async_generate_prompts(
        self,
        prompts: List[str],
        sampling_params: Dict[str, Any],
        **_kwargs  # Unused, for compatibility
    ) -> List[str]:
        """
        Generate from text prompts.
        
        Args:
            prompts: List of text prompts
            sampling_params: Sampling parameters
        
        Returns:
            List of generated texts
        """
        # Tokenize prompts
        all_input_ids = [
            self.tokenizer.encode(prompt)
            for prompt in prompts
        ]

        # Generate
        results = await self.engine.generate_batch(
            prompts=all_input_ids,
            sampling_params=sampling_params
        )

        return [text for text, _ in results]


# For Ray distributed deployment
def create_ray_vllm_actor(
    model_path: str,
    tensor_parallel_size: int = 1,
    **engine_args
):
    """
    Create a Ray actor wrapping AsyncVLLMEngine.

    Usage::

        import ray

        VLLMServer = create_ray_vllm_actor("meta-llama/Llama-3.1-8B-Instruct")
        server = VLLMServer.remote()
        ray.get(server.init_engine.remote())

        response, meta = ray.get(server.generate.remote(
            prompt_ids=[...],
            sampling_params={...},
            request_id="123",
        ))
    """
    if ray is None:
        raise ImportError(
            "ray is required for create_ray_vllm_actor. "
            "Install with: pip install mcpuniverse[vllm]"
        )

    @ray.remote(num_cpus=1)
    class RayVLLMServer(AsyncVLLMEngine):
        """Ray actor wrapping AsyncVLLMEngine for distributed deployment."""

        def __init__(self):
            super().__init__(
                model_path=model_path,
                tensor_parallel_size=tensor_parallel_size,
                **engine_args,
            )

    return RayVLLMServer


# ---------------------------------------------------------------------------
# SGLang counterpart — same public surface as AsyncVLLMEngine so callers
# can pick a backend by class name without other code changes.
# ---------------------------------------------------------------------------


@dataclass
class SGLangEngineConfig:
    """Configuration for SGLang engine.

    Mirrors `VLLMEngineConfig` field-by-field where the concepts map
    cleanly. SGLang-specific knobs go in ``engine_args``.
    """
    model_path: str
    tensor_parallel_size: int = 1
    dtype: str = "auto"
    trust_remote_code: bool = True
    max_model_len: Optional[int] = None  # forwarded as ``context_length``
    gpu_memory_utilization: float = 0.9  # forwarded as ``mem_fraction_static``
    random_seed: int = 42
    # Additional SGLang ``ServerArgs`` kwargs (forwarded as-is)
    engine_args: Dict[str, Any] = field(default_factory=dict)


class AsyncSGLangEngine:
    """Direct SGLang ``Engine`` wrapper (no HTTP serve).

    Same contract as `AsyncVLLMEngine`:
    - ``async generate(prompt_ids, sampling_params, request_id) -> (text, meta)``
    - ``async generate_batch(prompts, sampling_params, request_ids) -> [(text, meta)]``
    - ``async get_tokenizer()``
    - ``async shutdown()``

    Differences from vLLM (handled internally):
    - SGLang's ``Engine.async_generate`` returns ``meta_info`` with keys like
      ``finish_reason: {"type": "stop"|"length", ...}``, ``output_token_logprobs``
      (list of ``[logprob, token_id, _]`` tuples), ``completion_tokens`` etc.
      We normalize these to the same ``meta`` dict shape that ``TITOLLMWrapper``
      expects (output_tokens, finish_reason, logprobs, prompt_tokens,
      completion_tokens).
    - vLLM's ``max_tokens`` ↔ SGLang's ``max_new_tokens``. We accept either
      key in the input ``sampling_params`` and forward to SGLang as
      ``max_new_tokens``.
    """

    def __init__(
        self,
        model_path: str,
        tensor_parallel_size: int = 1,
        dtype: str = "auto",
        trust_remote_code: bool = True,
        max_model_len: Optional[int] = None,
        gpu_memory_utilization: float = 0.9,
        random_seed: int = 42,
        **engine_args,
    ):
        self.config = SGLangEngineConfig(
            model_path=model_path,
            tensor_parallel_size=tensor_parallel_size,
            dtype=dtype,
            trust_remote_code=trust_remote_code,
            max_model_len=max_model_len,
            gpu_memory_utilization=gpu_memory_utilization,
            random_seed=random_seed,
            engine_args=engine_args,
        )

        self.engine = None
        self.tokenizer = None
        self.max_model_len = max_model_len
        self._initialized = False

    async def init_engine(self):
        """Initialize the SGLang ``Engine`` lazily (no top-level import)."""
        if self._initialized:
            return

        try:
            # SGLang's Engine is exposed at the top level as a LazyImport;
            # importing from the concrete path is more deterministic.
            from sglang.srt.entrypoints.engine import Engine as _SGLangEngine  # pylint: disable=import-outside-toplevel
        except ImportError as exc:
            raise ImportError(
                "sglang is required for AsyncSGLangEngine. "
                "Install with: pip install 'sglang[all]' "
                "(note: SGLang has strict torch/sgl_kernel version requirements)"
            ) from exc

        # Map our common fields to SGLang ServerArgs.
        sglang_kwargs: Dict[str, Any] = {
            "model_path": self.config.model_path,
            "tp_size": self.config.tensor_parallel_size,
            "dtype": self.config.dtype,
            "trust_remote_code": self.config.trust_remote_code,
            "mem_fraction_static": self.config.gpu_memory_utilization,
            "random_seed": self.config.random_seed,
        }
        if self.config.max_model_len is not None:
            sglang_kwargs["context_length"] = self.config.max_model_len
        sglang_kwargs.update(self.config.engine_args)

        self.engine = _SGLangEngine(**sglang_kwargs)

        # SGLang Engine exposes ``tokenizer_manager.context_length`` etc.;
        # use it to fill in ``max_model_len`` if the caller didn't specify.
        if self.max_model_len is None:
            ctx = getattr(
                getattr(self.engine, "tokenizer_manager", None),
                "context_length",
                None,
            )
            if ctx:
                self.max_model_len = int(ctx)

        self._initialized = True
        logger.info(
            "[AsyncSGLangEngine] Initialized with max_model_len={}",
            self.max_model_len,
        )

    @staticmethod
    def _normalize_sampling_params(
        sampling_params: Dict[str, Any],
        max_new_default: int,
    ) -> Tuple[Dict[str, Any], bool]:
        """Map vLLM-style ``sampling_params`` to SGLang's expected keys.

        Returns ``(sglang_sp, return_logprob)``.
        """
        sp = dict(sampling_params) if sampling_params else {}
        return_logprob = bool(sp.pop("return_logprobs", False)) or bool(
            sp.pop("logprobs", False)
        )

        # vLLM uses ``max_tokens``; SGLang uses ``max_new_tokens``.
        if "max_new_tokens" not in sp:
            mt = sp.pop("max_tokens", None)
            sp["max_new_tokens"] = int(mt) if mt is not None else max_new_default
        else:
            sp["max_new_tokens"] = int(sp["max_new_tokens"])
            sp.pop("max_tokens", None)

        # vLLM uses ``stop`` (list of strings) — SGLang accepts ``stop`` too.
        # No remap needed for ``temperature``, ``top_p``, ``top_k``, ``seed``.
        return sp, return_logprob

    async def generate(
        self,
        prompt_ids: List[int],
        sampling_params: Dict[str, Any],
        request_id: Optional[str] = None,
    ) -> Tuple[str, Dict[str, Any]]:
        """Async generate from token IDs, returning ``(text, meta_info)``.

        Shape of ``meta_info`` matches :meth:`AsyncVLLMEngine.generate` so
        downstream ``TITOLLMWrapper`` consumers don't branch on backend.
        """
        if not self._initialized:
            await self.init_engine()

        max_new_default = max(
            1,
            (self.max_model_len or len(prompt_ids) + 1) - len(prompt_ids),
        )
        sp, return_logprob = self._normalize_sampling_params(
            sampling_params, max_new_default,
        )

        rid = request_id or str(uuid.uuid4())

        output = await self.engine.async_generate(
            input_ids=prompt_ids,
            sampling_params=sp,
            return_logprob=return_logprob,
            rid=rid,
        )

        # SGLang returns ``output`` as a dict (single-input case).
        # See sglang/srt/managers/io_struct.py::GenerateReqOutput.
        text = output.get("text", "") if isinstance(output, dict) else str(output)
        meta = output.get("meta_info", {}) if isinstance(output, dict) else {}

        output_tokens: List[int] = []
        logprobs: Optional[List[float]] = None
        if "output_token_logprobs" in meta:
            # Each entry is [logprob, token_id, _decoded_token]
            output_tokens = [item[1] for item in meta["output_token_logprobs"]]
            if return_logprob:
                logprobs = [item[0] for item in meta["output_token_logprobs"]]
        elif "output_ids" in meta:
            output_tokens = list(meta["output_ids"])

        finish_reason_raw = meta.get("finish_reason")
        if isinstance(finish_reason_raw, dict):
            # SGLang shape: {"type": "stop" | "length" | "abort", "matched": ...}
            finish_reason = finish_reason_raw.get("type")
        else:
            finish_reason = finish_reason_raw

        meta_info = {
            "output_tokens": output_tokens,
            "finish_reason": finish_reason,
            "logprobs": logprobs,
            "prompt_tokens": meta.get("prompt_tokens", len(prompt_ids)),
            "completion_tokens": meta.get(
                "completion_tokens", len(output_tokens),
            ),
        }

        return text, meta_info

    async def generate_batch(
        self,
        prompts: List[List[int]],
        sampling_params: Dict[str, Any],
        request_ids: Optional[List[str]] = None,
    ) -> List[Tuple[str, Dict[str, Any]]]:
        """Generate concurrently for multiple prompts."""
        if request_ids is None:
            request_ids = [str(uuid.uuid4()) for _ in prompts]
        tasks = [
            self.generate(p, sampling_params, rid)
            for p, rid in zip(prompts, request_ids)
        ]
        return await asyncio.gather(*tasks)

    async def get_tokenizer(self):
        """Get the underlying HF tokenizer used by SGLang."""
        if not self._initialized:
            raise RuntimeError("Engine not initialized. Call init_engine() first.")
        # SGLang exposes the tokenizer via ``tokenizer_manager.tokenizer``.
        tm = getattr(self.engine, "tokenizer_manager", None)
        if tm is not None and getattr(tm, "tokenizer", None) is not None:
            return tm.tokenizer
        # Older / future SGLang versions might rename: try a fallback.
        tok = getattr(self.engine, "tokenizer", None)
        if tok is not None:
            return tok
        raise RuntimeError(
            "Could not locate tokenizer on SGLang Engine; "
            "check sglang version compatibility."
        )

    async def shutdown(self):
        """Shutdown the engine (calls SGLang's process-tree kill)."""
        if self.engine is None:
            return
        try:
            self.engine.shutdown()
        except Exception as exc:  # pylint: disable=broad-except
            logger.warning("[AsyncSGLangEngine] shutdown raised: {}", exc)
        finally:
            self.engine = None
            self._initialized = False


def create_ray_sglang_actor(
    model_path: str,
    tensor_parallel_size: int = 1,
    **engine_args,
):
    """Create a Ray actor wrapping `AsyncSGLangEngine`.

    Symmetric to :func:`create_ray_vllm_actor`. See that function's
    docstring for usage; substitute ``SGLangServer`` for ``VLLMServer``.
    """
    if ray is None:
        raise ImportError(
            "ray is required for create_ray_sglang_actor. "
            "Install with: pip install 'sglang[all]' ray"
        )

    @ray.remote(num_cpus=1)
    class RaySGLangServer(AsyncSGLangEngine):
        """Ray actor wrapping AsyncSGLangEngine for distributed deployment."""

        def __init__(self):
            super().__init__(
                model_path=model_path,
                tensor_parallel_size=tensor_parallel_size,
                **engine_args,
            )

    return RaySGLangServer


# ---------------------------------------------------------------------------
# SGLang HTTP-client engine — for callers that already have a SGLang server
# running in a separate process (e.g. slime, which spawns SGLang via
# ``sgl_router`` independently of the trainer). Same async ``generate``
# contract as `AsyncSGLangEngine` / `AsyncVLLMEngine`, so
# ``TITOLLMWrapper`` can consume it without branching.
# ---------------------------------------------------------------------------


class AsyncSGLangHTTPEngine:
    """HTTP-client adapter for a SGLang server running in another process.

    Use this when the SGLang Engine is owned by a different lifecycle
    manager (e.g. ``sgl_router``) and the trainer only needs a thin
    ``TITOLLMWrapper``-compatible client. For in-process SGLang, use
    `AsyncSGLangEngine` instead.

    Per-trajectory state:
    - ``response_log_probs`` accumulates per-token log_probs across all
      ``generate`` calls in a single agent loop (multi-turn TITO). The
      caller (typically the postprocess layer) reads this list at the
      end of a rollout to attach log_probs to the training sample for
      importance sampling. The accumulator is **per-instance**, so use
      one engine instance per trajectory (slime does exactly this in
      its ``_create_llm_for_slime`` path).

    Concurrency:
    - The optional ``semaphore`` is acquired around the HTTP POST so the
      caller can bound the number of concurrent in-flight requests to
      the SGLang server (typical for slime's many parallel rollouts).

    SGLang server contract:
    - POSTs ``{"input_ids": [...], "sampling_params": {...},
      "return_logprob": True}`` to ``<url>/generate``.
    - Reads ``meta_info["output_token_logprobs"]`` (list of
      ``[logprob, token_id, decoded]`` tuples) to recover both
      ``output_tokens`` and ``logprobs``.
    """

    def __init__(
        self,
        url: str,
        semaphore: Optional[asyncio.Semaphore] = None,
        post_fn: Optional[Any] = None,
    ):
        """
        Args:
            url: Full URL of the SGLang ``/generate`` endpoint
                 (e.g. ``"http://localhost:30000/generate"``).
            semaphore: Optional asyncio semaphore to bound concurrent
                       HTTP requests; if None, no bounding is applied.
            post_fn: Injectable async POST function ``post_fn(url, payload)
                     -> dict``. Defaults to a lightweight aiohttp wrapper
                     when None. Useful for testing.
        """
        self._url = url
        self._semaphore = semaphore
        self._post_fn = post_fn
        # Per-instance log_probs accumulator (read by the postprocess layer
        # at end-of-trajectory). Reset by ``reset()`` or by creating a new
        # engine instance per trajectory.
        self.response_log_probs: List[float] = []

    def reset(self) -> None:
        """Clear accumulated ``response_log_probs`` (call between trajectories
        if you reuse the engine instance, which is rare — typical pattern
        is one instance per trajectory).
        """
        self.response_log_probs.clear()

    async def _post(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        if self._post_fn is not None:
            return await self._post_fn(self._url, payload)
        # Lazy aiohttp import (avoid hard dep when tests don't need it).
        import aiohttp  # pylint: disable=import-outside-toplevel
        async with aiohttp.ClientSession() as session:
            async with session.post(self._url, json=payload) as resp:
                resp.raise_for_status()
                return await resp.json()

    async def generate(
        self,
        prompt_ids: List[int],
        sampling_params: Dict[str, Any],
        request_id: Optional[str] = None,  # pylint: disable=unused-argument
    ) -> Tuple[str, Dict[str, Any]]:
        """Generate from token IDs over HTTP.

        Returns ``(text, meta)`` where ``meta`` matches the contract of
        :meth:`AsyncVLLMEngine.generate` (keys: ``output_tokens``,
        ``finish_reason``, ``logprobs``, ``prompt_tokens``,
        ``completion_tokens``), plus any extra SGLang-specific fields
        passed through from ``meta_info``.
        """
        payload = {
            "input_ids": prompt_ids,
            "sampling_params": sampling_params,
            "return_logprob": True,
        }
        if self._semaphore is not None:
            async with self._semaphore:
                output = await self._post(payload)
        else:
            output = await self._post(payload)

        text = output.get("text", "")
        meta = output.get("meta_info", {}) if isinstance(output, dict) else {}

        output_tokens: List[int] = []
        output_log_probs: List[float] = []
        if "output_token_logprobs" in meta:
            output_log_probs = [item[0] for item in meta["output_token_logprobs"]]
            output_tokens = [item[1] for item in meta["output_token_logprobs"]]

        # Accumulate log_probs across multi-turn calls so the postprocess
        # layer can attach per-token log_probs to the training sample.
        self.response_log_probs.extend(output_log_probs)

        finish_reason_raw = meta.get("finish_reason")
        if isinstance(finish_reason_raw, dict):
            finish_reason = finish_reason_raw.get("type")
        else:
            finish_reason = finish_reason_raw

        # Pass through SGLang-specific meta fields, but EXCLUDE the keys we
        # explicitly normalize (output_token_logprobs is consumed above;
        # finish_reason/prompt_tokens/completion_tokens are normalized into
        # our canonical schema). Putting passthrough first then normalized
        # keys ensures the canonical values win on overlap.
        _consumed = {"output_token_logprobs", "finish_reason",
                     "prompt_tokens", "completion_tokens"}
        meta_info = {
            **{k: v for k, v in meta.items() if k not in _consumed},
            "output_tokens": output_tokens,
            "finish_reason": finish_reason,
            "logprobs": output_log_probs or None,
            "prompt_tokens": meta.get("prompt_tokens", len(prompt_ids)),
            "completion_tokens": meta.get("completion_tokens", len(output_tokens)),
        }

        return text, meta_info
