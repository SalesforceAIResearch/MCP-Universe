"""Unit tests for ``flatten_dataproto_metrics_inplace``.

Guards the regression where ``DataProto.concat`` merges per-DP-rank
``meta_info["metrics"]`` into a ragged ``list[list[float]]`` (caused by
dynamic-bsz emitting different numbers of micro-batches per rank), which
then crashes ``verl.utils.metric.utils.reduce_metrics → np.mean(val)``
with::

    ValueError: setting an array element with a sequence.
    The detected shape was (2,) + inhomogeneous part.

The helper lives in ``mcpuniverse.rl.integrations.verl.utils`` and is
called from:
- worker side: ``MCPMegatronDetachActorWorker.update_actor`` (defensive
  layer for nested tensor/array within one worker)
- trainer side: ``MCPFullyAsyncTrainer._fit_update_actor`` (the *real*
  fix, since concat re-nests per-worker lists after the worker wrapper
  returns).
"""

from types import SimpleNamespace

import numpy as np
import pytest

# Heavy training-stack deps are optional extras (not installed in minimal CI).
# utils imports ray + verl at module load; skip gracefully when unavailable.
pytest.importorskip("torch")
pytest.importorskip("ray")
pytest.importorskip("verl")

import torch

# Public location (controller-side users import from here).
from mcpuniverse.rl.integrations.verl.utils import (
    flatten_and_reduce_metrics_inplace,
    flatten_dataproto_metrics_inplace,
)
# Worker-side re-export (kept for callsite in megatron worker module).
from mcpuniverse.rl.integrations.verl.fully_async.mcp_megatron_async_workers import (
    _flatten_dataproto_metrics_inplace,
)


def test_worker_and_utils_aliases_point_to_same_function():
    """The worker module re-exports the canonical helper from ``verl/utils``."""
    assert flatten_dataproto_metrics_inplace is _flatten_dataproto_metrics_inplace


def _proto(metrics):
    return SimpleNamespace(meta_info={"metrics": metrics})


def test_flatten_handles_dp_rank_imbalance_after_concat():
    # ``DataProto.concat`` produces this exact structure when two DP ranks
    # emit metric lists of different lengths.
    proto = _proto({
        "actor/pg_loss": [[0.5, 0.6, 0.7], [0.4, 0.5]],
        "actor/entropy": [[0.1], [0.2, 0.3]],
    })

    flatten_dataproto_metrics_inplace(proto)

    assert proto.meta_info["metrics"] == {
        "actor/pg_loss": [0.5, 0.6, 0.7, 0.4, 0.5],
        "actor/entropy": [0.1, 0.2, 0.3],
    }
    # And np.mean works downstream without inhomogeneous-shape error.
    for val in proto.meta_info["metrics"].values():
        assert isinstance(float(np.mean(val)), float)


def test_flatten_keeps_flat_list_unchanged():
    proto = _proto({"actor/pg_loss": [0.5, 0.6, 0.7]})
    flatten_dataproto_metrics_inplace(proto)
    assert proto.meta_info["metrics"] == {"actor/pg_loss": [0.5, 0.6, 0.7]}


def test_flatten_promotes_scalar_to_list():
    # Some metrics arrive as scalar (single value, single rank).
    proto = _proto({"actor/lr": 0.0001})
    flatten_dataproto_metrics_inplace(proto)
    assert proto.meta_info["metrics"] == {"actor/lr": [0.0001]}


def test_flatten_handles_torch_tensor_and_numpy():
    proto = _proto({
        "actor/from_tensor": [torch.tensor([1.0, 2.0]), torch.tensor([3.0])],
        "actor/from_numpy": [np.array([4.0, 5.0]), np.array([6.0])],
        "actor/scalar_tensor": torch.tensor(7.0),
    })

    flatten_dataproto_metrics_inplace(proto)

    assert proto.meta_info["metrics"]["actor/from_tensor"] == [1.0, 2.0, 3.0]
    assert proto.meta_info["metrics"]["actor/from_numpy"] == [4.0, 5.0, 6.0]
    assert proto.meta_info["metrics"]["actor/scalar_tensor"] == [7.0]


def test_flatten_noop_when_no_metrics_field():
    proto = SimpleNamespace(meta_info={})
    flatten_dataproto_metrics_inplace(proto)
    assert proto.meta_info == {}


def test_flatten_noop_when_meta_info_missing():
    proto = SimpleNamespace()
    flatten_dataproto_metrics_inplace(proto)
    assert not hasattr(proto, "meta_info")


def test_flatten_noop_on_none_proto():
    # Should not crash on a None result (defensive).
    flatten_dataproto_metrics_inplace(None)


def test_flatten_preserves_non_numeric_unknown_structures():
    # If someone packs a non-numeric value (dict / object), we leave it
    # alone so the downstream reducer fails with a clearer error rather
    # than mangling data.
    sentinel = {"unexpected": "structure"}
    proto = _proto({"meta/extra": sentinel})
    flatten_dataproto_metrics_inplace(proto)
    assert proto.meta_info["metrics"]["meta/extra"] == [sentinel]


@pytest.mark.parametrize(
    "raw,expected",
    [
        ([], []),
        ([[]], []),
        ([[1.0]], [1.0]),
        ([[1.0, 2.0], [], [3.0]], [1.0, 2.0, 3.0]),
        ([[[1.0, 2.0]], [[3.0]]], [1.0, 2.0, 3.0]),  # deeply nested
    ],
)
def test_flatten_parametrised_shapes(raw, expected):
    proto = _proto({"actor/x": raw})
    flatten_dataproto_metrics_inplace(proto)
    assert proto.meta_info["metrics"]["actor/x"] == expected


# ---------------------------------------------------------------------------
# Trainer-side integration: ensures ``flatten_and_reduce_metrics_inplace``
# flattens BEFORE calling ``reduce_metrics``. This is the REAL fix
# (worker-side flatten alone is insufficient because ``DataProto.concat``
# re-nests per-worker lists during ray dispatch collection).
#
# ``MCPFullyAsyncTrainer._fit_update_actor`` and ``_fit_update_critic``
# delegate to ``flatten_and_reduce_metrics_inplace``; we exercise the
# module-level helper directly to avoid ray's class-method tracing
# wrapper (which intercepts all method access on actor-ish classes).
# ---------------------------------------------------------------------------


def test_flatten_and_reduce_handles_ragged_per_rank_lists():
    """Exact post-concat shape (``list[list[float]]`` of unequal lengths)
    that DataProto.concat produces on Megatron + DP>1 + dynamic_bsz must
    reduce to scalar means without crashing.
    """
    ragged_metrics = {
        "actor/pg_loss": [[0.5, 0.6, 0.7], [0.4, 0.5]],
        "actor/entropy": [0.1, 0.2],
    }
    actor_output = SimpleNamespace(meta_info={"metrics": ragged_metrics})
    target = {}

    flatten_and_reduce_metrics_inplace(actor_output, target)

    # ragged [[3 items], [2 items]] -> flat [5 items] -> mean = 0.54
    assert target["actor/pg_loss"] == pytest.approx(0.54)
    # already flat -> mean = 0.15
    assert target["actor/entropy"] == pytest.approx(0.15)


def test_flatten_and_reduce_supports_max_min_keys():
    """verl's ``reduce_metrics`` switches to np.max/np.min for keys whose
    name contains "max"/"min". The flatten-then-reduce path must respect that.
    """
    proto = SimpleNamespace(meta_info={"metrics": {
        "actor/max_clip_ratio": [[0.1, 0.2], [0.5, 0.3]],
        "actor/min_clip_ratio": [[0.4, 0.1], [0.6, 0.05]],
    }})
    target = {}

    flatten_and_reduce_metrics_inplace(proto, target)

    assert target["actor/max_clip_ratio"] == pytest.approx(0.5)
    assert target["actor/min_clip_ratio"] == pytest.approx(0.05)


def test_flatten_and_reduce_preserves_existing_target_keys():
    """``target.update(reduced)`` semantics: pre-existing keys in target
    (set by earlier pipeline stages) must survive.
    """
    proto = SimpleNamespace(meta_info={"metrics": {"actor/pg_loss": [[0.5], [0.7]]}})
    target = {"training/global_step": 42, "perf/rollout_time": 12.34}

    flatten_and_reduce_metrics_inplace(proto, target)

    assert target["training/global_step"] == 42
    assert target["perf/rollout_time"] == pytest.approx(12.34)
    assert target["actor/pg_loss"] == pytest.approx(0.6)


def test_flatten_and_reduce_handles_flat_already_reduced_input():
    """If upstream concat happened to produce a flat list (single rank
    or balanced micro-batches), the function should still work correctly.
    """
    proto = SimpleNamespace(meta_info={"metrics": {"actor/lr": [1e-5, 1e-5, 1e-5]}})
    target = {}

    flatten_and_reduce_metrics_inplace(proto, target)

    assert target["actor/lr"] == pytest.approx(1e-5)


def test_trainer_module_exports_helper():
    """Sanity-check that ``mcp_async_trainer`` actually re-imports the
    helpers it documents in ``_fit_update_actor``'s docstring; if this
    import fails the trainer fit step will explode at runtime.
    """
    from mcpuniverse.rl.integrations.verl.fully_async import mcp_async_trainer

    assert mcp_async_trainer.flatten_and_reduce_metrics_inplace \
        is flatten_and_reduce_metrics_inplace
    assert mcp_async_trainer.flatten_dataproto_metrics_inplace \
        is flatten_dataproto_metrics_inplace
