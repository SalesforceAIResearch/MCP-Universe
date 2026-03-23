# pylint: disable=protected-access

"""
MCP Parameter Synchronizer with actual weight sync implementation.

The upstream ParameterSynchronizer (verl.experimental.fully_async_policy.param_sync)
has the weight sync code commented out because:
  - sync_rollout_weights targets DetachAsyncRolloutWorker's local inference engine
  - But in fully async mode, the rollout uses ServerAdapter (no local engine)
  - get_inference_model(ServerAdapter) fails -> upstream commented out the sync

This is a standalone reimplementation (NOT a subclass, since Ray forbids
inheriting from @ray.remote classes) that adds the actual NCCL broadcast
from actor workers to rollout workers.  It works because MCPAsyncRolloutWorker
overrides sync_rollout_weights() to use ServerAdapter.update_weights() (CUDA IPC)
instead of get_inference_model().load_weights().

Works with both vLLM and SGLang backends — both ServerAdapter implementations
expose the same update_weights() interface.
"""

import logging
import time

import ray
from ray.util.collective import collective

from verl.utils.device import get_nccl_backend

logger = logging.getLogger(__name__)


@ray.remote
class MCPParameterSynchronizer:
    """Parameter synchronizer that actually performs weight sync.

    Standalone reimplementation of ParameterSynchronizer with the weight
    sync code un-commented.  All init/utility methods are copied from
    the upstream class since Ray does not allow actor class inheritance.
    """

    def __init__(self, config, trainer, rollouter, mq):
        self.config = config
        self.trainer = trainer
        self.rollouter = rollouter
        self.mq_client = mq

        self.actor_wg = ray.get(trainer.get_actor_wg.remote())
        self.rollout_wg = ray.get(rollouter.get_rollout_wg.remote())

        self.weights_info = None
        self.sync_group_initialized = False
        self.sync_group_name = "actor_rollout"
        self.wait_last_update = None
        self.wait_last_resume = None
        self.validate_task = None

        # Incremented on each sync; used to track which model version rollout is using.
        self.current_version = 0

        self._init_weights_info()
        self._init_sync_group()

        if self.config.async_training.checkpoint_engine.enable:
            self._init_actor_rollout_checkpoint_engine()

    def get_current_param_version(self) -> int:
        """Get current parameter version number."""
        return self.current_version

    def get_weights_info(self):
        """Get weights info."""
        return self.weights_info

    def _init_weights_info(self):
        # Fetch weight metadata (name/shape/dtype) from actor workers so rollout
        # workers can pre-allocate NCCL receive buffers of the right size.
        self.weights_info = self.actor_wg.get_actor_weights_info()[0]
        self.rollout_wg.set_actor_weights_info(self.weights_info)

    def _init_sync_group(self):
        # Create a single NCCL broadcast group spanning actor + rollout workers.
        # Ranks [0..N_actor-1] are actor workers (broadcast src=0);
        # ranks [N_actor..N_total-1] are rollout workers (receivers).
        print("[MCPParameterSynchronizer] Initializing parameter synchronization group...")
        actor_rollout_workers = self.actor_wg.workers + self.rollout_wg.workers
        n_workers = len(actor_rollout_workers)
        if self.config.trainer.device == "npu":
            # NPU (Ascend) uses a custom weight sync group instead of Ray collective.
            master_address = ray.get(self.actor_wg.workers[0]._get_node_ip.remote()).strip("[]")
            master_port = ray.get(self.actor_wg.workers[0]._get_free_port.remote())
            self.actor_wg.create_weight_sync_group(
                master_address,
                master_port,
                0,
                n_workers,
            )
            ray.get(
                self.rollout_wg.create_weight_sync_group(
                    master_address,
                    master_port,
                    len(self.actor_wg.workers),  # rollout ranks follow actor ranks
                    n_workers,
                )
            )
        else:
            collective.create_collective_group(
                actor_rollout_workers,
                n_workers,
                list(range(0, n_workers)),
                backend=get_nccl_backend(),
                group_name=self.sync_group_name,
            )

    def _init_actor_rollout_checkpoint_engine(self):
        # Checkpoint engine syncs weights via filesystem instead of NCCL.
        # rank_offset separates actor and rollout checkpoint files.
        ray.get(
            self.actor_wg.init_checkpoint_engine(
                rank_offset=0,
                actor_num=len(self.actor_wg.workers),
                rollout_num=len(self.rollout_wg.workers),
            )
        )
        ray.get(
            self.rollout_wg.init_checkpoint_engine(
                rank_offset=len(self.actor_wg.workers),
                actor_num=len(self.actor_wg.workers),
                rollout_num=len(self.rollout_wg.workers),
            )
        )

    def sync_weights(self, version, validate=False, global_steps=0, use_trainer_do_validate=False):
        """Sync weights between trainer and rollouter, with actual weight transfer.

        Flow:
          1. Pause rollouter (cancel in-flight, wait for completion)
          2. Update MQ param version
          3. NCCL broadcast actor weights -> rollout workers -> inference servers (via IPC)
          4. Trigger validation (if requested)
          5. Resume rollouter
        """
        start_time = time.time()

        self.current_version = version

        # Pause before weight sync: inference using the old weights must finish
        # before the NCCL broadcast overwrites them.
        ray.get(self.rollouter.pause.remote())

        print(f"[MCPParameterSynchronizer] rollout paused. cost {time.time() - start_time:.2f} seconds")

        # Update the queue's param version so newly generated trajectories
        # are tagged with the correct version for staleness tracking.
        self.mq_client.update_param_version_sync(version)

        pause_time = time.time()

        # NCCL broadcast: this is the code that upstream commented out.
        # Actor side: DetachActorWorker.sync_rollout_weights() gathers FSDP shards
        #   into full tensors and broadcasts them as src_rank=0.
        # Rollout side: MCPAsyncRolloutWorker.sync_rollout_weights() receives via
        #   NCCL and pushes to the inference server via ServerAdapter.update_weights()
        #   (CUDA IPC), bypassing the upstream get_inference_model() path that fails.
        use_checkpoint_engine = self.config.async_training.checkpoint_engine.enable
        if use_checkpoint_engine:
            self.actor_wg.sync_rollout_weights_by_checkpoint(self.sync_group_name)
            ray.get(self.rollout_wg.sync_rollout_weights_by_checkpoint(self.sync_group_name))
        else:
            # actor_wg call is not awaited so actor and rollout can overlap;
            # rollout_wg is awaited to ensure all weights are received before resuming.
            self.actor_wg.sync_rollout_weights(self.sync_group_name)
            ray.get(self.rollout_wg.sync_rollout_weights(self.sync_group_name))

        end_time = time.time()
        print(
            f"[MCPParameterSynchronizer] sync_weights success. cost {end_time - start_time:.2f} seconds, "
            f"pause:{pause_time - start_time:.2f}s, sync:{end_time - pause_time:.2f}s"
        )

        print(f"[MCPParameterSynchronizer] validate: {validate}, use_trainer_do_validate: {use_trainer_do_validate}")
        if validate and use_trainer_do_validate:
            print("[MCPParameterSynchronizer] use trainer to do validate")
            self.validate_task = self.trainer._validate_process.remote()
        else:
            self.validate_task = None

        # Async: update rollout's param version and resume generation.
        # resume depends on update completing (passed as dependency ref) to preserve ordering.
        # Both are fire-and-forget here; wait_last_valid() blocks before the next sync.
        self.wait_last_update = self.rollouter.update_param_version.remote(
            version, validate, global_steps, use_trainer_do_validate
        )
        self.wait_last_resume = self.rollouter.resume.remote(self.wait_last_update)

    def wait_last_valid(self):
        """Block until the previous sync's async tails complete: param version update,
        resume, and optional validation. Must be called before starting the next sync
        to avoid overlapping pause/resume cycles."""
        print("[MCPParameterSynchronizer] Waiting last sync and validate...")
        start_time = time.time()
        if self.wait_last_update:
            ray.get(self.wait_last_update)
        if self.wait_last_resume:
            ray.get(self.wait_last_resume)
        if self.validate_task:
            ray.get(self.validate_task)
        print(f"[MCPParameterSynchronizer] Wait last validate cost: {time.time() - start_time:.2f} seconds")

    def rollouter_save_checkpoint(self, local_global_step_folder: str):
        """Trigger rollouter to save its checkpoint (dataloader state)."""
        print(f"[MCPParameterSynchronizer] Triggering checkpoint save at {local_global_step_folder} ...")
        return ray.get(self.rollouter.save_checkpoint.remote(local_global_step_folder))
