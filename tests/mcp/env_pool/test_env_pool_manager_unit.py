"""Unit tests for EnvPoolManager config compatibility behavior."""

import asyncio
import copy
import time

from mcpuniverse.mcp.env_pool import EnvConfig, EnvInfo, EnvStatus
from mcpuniverse.mcp.env_pool.base import (
    BaseProvisioner,
    env_configs_compatible,
)
from mcpuniverse.mcp.env_pool.manager import EnvPoolManager


class FakeProvisioner(BaseProvisioner):
    def __init__(self):
        self.destroyed = []
        self.created_configs = []

    async def create(self, env_id: str, config: EnvConfig) -> EnvInfo:
        cfg = copy.deepcopy(config)
        self.created_configs.append(cfg)
        return EnvInfo(
            env_id=env_id,
            status=EnvStatus.READY,
            gateway_address=f"http://gateway/{env_id}",
            config=cfg,
        )

    async def destroy(self, env_id: str) -> bool:
        self.destroyed.append(env_id)
        return True

    async def reset(self, env_id: str) -> bool:
        return True

    async def health_check(self, env_id: str) -> bool:
        return True

    async def get_info(self, env_id: str):
        return None


class FlakyProvisioner(FakeProvisioner):
    def __init__(self, fail_after: int):
        super().__init__()
        self.fail_after = fail_after

    async def create(self, env_id: str, config: EnvConfig) -> EnvInfo:
        if len(self.created_configs) >= self.fail_after:
            raise RuntimeError("provision unavailable")
        return await super().create(env_id, config)


def test_env_config_compatibility_uses_full_contract():
    base = EnvConfig(
        servers=["github", "browser"],
        dockerfile_path="Dockerfile",
        env_vars={"TOKEN": "x"},
        volumes=["/host:/ctr"],
        cpu_limit="2",
    )

    same = EnvConfig(
        servers=["browser", "github"],
        dockerfile_path="Dockerfile",
        env_vars={"TOKEN": "x"},
        volumes=["/host:/ctr"],
        cpu_limit="2",
    )
    different_env = copy.deepcopy(base)
    different_env.env_vars = {"TOKEN": "y"}
    different_resources = copy.deepcopy(base)
    different_resources.cpu_limit = "8"

    assert env_configs_compatible(base, same)
    assert not env_configs_compatible(base, different_env)
    assert not env_configs_compatible(base, different_resources)


def test_acquire_evicts_incompatible_ready_env_at_capacity_for_autoscale():
    async def scenario():
        provisioner = FakeProvisioner()
        manager = EnvPoolManager(
            provisioner=provisioner,
            max_pool_size=2,
            auto_scale=True,
            acquisition_timeout=0.01,
        )
        config_a = EnvConfig(
            servers=["github"],
            dockerfile_path="Dockerfile",
            env_vars={"TOKEN": "x"},
        )
        config_b = EnvConfig(
            servers=["browser"],
            dockerfile_path="Dockerfile",
            env_vars={"TOKEN": "x"},
        )

        await manager.provision(
            num_envs=2,
            config=config_a,
            parallel=False,
            reuse_existing=False,
        )

        env = await manager.acquire(
            agent_id="agent-browser",
            timeout=0.01,
            config=config_b,
        )

        assert env.config.servers == ["browser"]
        assert provisioner.destroyed
        stats = manager.get_stats()
        assert stats.total_envs == 2
        assert stats.in_use_envs == 1
        assert stats.ready_envs == 1

    asyncio.run(scenario())


def test_acquire_autoprovisions_immediately_when_pool_has_capacity():
    async def scenario():
        provisioner = FakeProvisioner()
        manager = EnvPoolManager(
            provisioner=provisioner,
            max_pool_size=1,
            auto_scale=True,
            acquisition_timeout=10.0,
        )

        start = time.monotonic()
        env = await manager.acquire(
            agent_id="agent-first",
            timeout=10.0,
            config=EnvConfig(servers=["github"]),
        )

        assert env.assigned_agent == "agent-first"
        assert time.monotonic() - start < 1.0

    asyncio.run(scenario())


def test_acquire_waits_for_compatible_release_before_autoprovisioning():
    async def scenario():
        provisioner = FakeProvisioner()
        manager = EnvPoolManager(
            provisioner=provisioner,
            max_pool_size=2,
            auto_scale=True,
            acquisition_timeout=1.0,
        )
        config = EnvConfig(servers=["github"])
        await manager.provision(
            num_envs=1,
            config=config,
            parallel=False,
            reuse_existing=False,
        )
        first = await manager.acquire(
            agent_id="agent-first",
            timeout=1.0,
            config=config,
        )

        acquire_task = asyncio.create_task(manager.acquire(
            agent_id="agent-second",
            timeout=1.0,
            config=config,
        ))
        await asyncio.sleep(0.05)
        assert not acquire_task.done()
        assert len(provisioner.created_configs) == 1

        await manager.release(first.env_id)
        second = await acquire_task

        assert second.env_id == first.env_id
        assert second.assigned_agent == "agent-second"
        assert len(provisioner.created_configs) == 1

    asyncio.run(scenario())


def test_destroy_reuse_policy_queues_then_background_destroys():
    async def scenario():
        provisioner = FakeProvisioner()
        manager = EnvPoolManager(
            provisioner=provisioner,
            max_pool_size=2,
            auto_scale=True,
            acquisition_timeout=1.0,
            reuse_policy="destroy",
        )
        env = await manager.acquire(
            agent_id="agent-first",
            timeout=1.0,
            config=EnvConfig(servers=["github"]),
        )

        # release() is now FAST + async: it marks PENDING_DESTROY and enqueues,
        # NOT inline docker rm. The env still counts toward capacity (so a slow
        # teardown backpressures new acquires).
        assert await manager.release(env.env_id)
        assert manager._envs[env.env_id].status == EnvStatus.PENDING_DESTROY  # pylint: disable=protected-access
        assert manager.get_stats().total_envs == 1
        assert provisioner.destroyed == []

        # The background destroyer does the actual removal off the critical path.
        manager.start_destroyer()
        await asyncio.sleep(0.1)

        stats = manager.get_stats()
        assert stats.total_envs == 0
        assert stats.ready_envs == 0
        assert provisioner.destroyed == [env.env_id]
        await manager.cleanup()

    asyncio.run(scenario())


def test_trimmed_cache_reuse_policy_caps_ready_envs():
    async def scenario():
        provisioner = FakeProvisioner()
        manager = EnvPoolManager(
            provisioner=provisioner,
            max_pool_size=3,
            auto_scale=True,
            acquisition_timeout=1.0,
            reuse_policy="trimmed_cache",
            max_ready_envs=1,
        )
        envs = await asyncio.gather(*[
            manager.acquire(
                agent_id=f"agent-{i}",
                timeout=1.0,
                config=EnvConfig(servers=["github"], dockerfile_path=f"Dockerfile.{i}"),
            )
            for i in range(2)
        ])

        assert await manager.release(envs[0].env_id)  # under quota -> cached
        assert await manager.release(envs[1].env_id)  # over quota -> queued destroy

        # First stays cached/ready; second is queued for background destroy.
        assert manager.get_stats().ready_envs == 1
        assert manager._envs[envs[1].env_id].status == EnvStatus.PENDING_DESTROY  # pylint: disable=protected-access

        manager.start_destroyer()
        await asyncio.sleep(0.1)

        stats = manager.get_stats()
        assert stats.total_envs == 1      # cached one remains
        assert stats.ready_envs == 1
        assert provisioner.destroyed == [envs[1].env_id]
        await manager.cleanup()

    asyncio.run(scenario())


def test_destroy_policy_provisions_immediately_without_reuse_wait():
    async def scenario():
        provisioner = FakeProvisioner()
        manager = EnvPoolManager(
            provisioner=provisioner,
            max_pool_size=4,
            auto_scale=True,
            acquisition_timeout=1.0,
            reuse_policy="destroy",
        )
        config = EnvConfig(servers=["github"], dockerfile_path="Dockerfile")
        first = await manager.acquire(agent_id="a1", timeout=1.0, config=config)

        # A compatible env exists but is busy. Under destroy it will never be
        # reused (release tears it down), so acquire must provision a new env
        # immediately instead of stalling for the reuse-wait slice.
        start = time.monotonic()
        second = await manager.acquire(agent_id="a2", timeout=1.0, config=config)
        elapsed = time.monotonic() - start

        assert second.env_id != first.env_id
        assert elapsed < 0.5
        assert len(provisioner.created_configs) == 2

    asyncio.run(scenario())


class SlowDestroyProvisioner(FakeProvisioner):
    """Provisioner whose destroy() sleeps, to exercise teardown cancellation."""

    def __init__(self, delay: float):
        super().__init__()
        self.delay = delay

    async def destroy(self, env_id: str) -> bool:
        await asyncio.sleep(self.delay)
        return await super().destroy(env_id)


def test_cancelled_destroy_still_completes_bookkeeping_no_phantom():
    """A teardown cancelled mid-flight (e.g. by cleanup_timeout) must NOT leave
    a phantom env in the pool: the shielded destroy completes the docker rm AND
    the _envs pop / total_envs decrement, so capacity accounting stays correct.
    Previously the cancel removed the container but left the env in _envs,
    clogging the pool until it stalled."""
    async def scenario():
        provisioner = SlowDestroyProvisioner(delay=0.3)
        manager = EnvPoolManager(
            provisioner=provisioner,
            max_pool_size=2,
            auto_scale=True,
            acquisition_timeout=1.0,
            reuse_policy="destroy",
        )
        env = await manager.acquire(
            agent_id="a", timeout=1.0, config=EnvConfig(servers=["github"]),
        )
        assert manager.get_stats().total_envs == 1

        task = asyncio.create_task(manager.destroy(env.env_id))
        await asyncio.sleep(0.05)   # enter the shielded teardown
        task.cancel()               # simulate cleanup_timeout cancelling release
        try:
            await task
        except asyncio.CancelledError:
            pass

        # The shielded teardown must still finish on the loop.
        await asyncio.sleep(0.6)

        stats = manager.get_stats()
        assert stats.total_envs == 0, f"phantom leak: total_envs={stats.total_envs}"
        assert env.env_id not in manager._envs  # pylint: disable=protected-access
        assert provisioner.destroyed == [env.env_id]

    asyncio.run(scenario())


def test_pending_destroy_backpressures_new_acquire():
    """PENDING_DESTROY envs count toward capacity: while the pool is full of
    not-yet-destroyed envs, a new (incompatible) acquire is blocked — this is
    the implicit backpressure that keeps creates from outrunning destroys.
    Once the background destroyer frees the slot, the acquire succeeds."""
    async def scenario():
        provisioner = FakeProvisioner()
        manager = EnvPoolManager(
            provisioner=provisioner,
            max_pool_size=1,
            auto_scale=True,
            acquisition_timeout=0.3,
            reuse_policy="destroy",
        )
        env = await manager.acquire(
            agent_id="a", timeout=1.0,
            config=EnvConfig(servers=["github"], dockerfile_path="D.a"),
        )
        assert await manager.release(env.env_id)  # -> PENDING_DESTROY, pool 1/1

        # New acquire for a different image can't provision: pool is full of the
        # pending-destroy env (which is not reusable / not ready) -> times out.
        timed_out = False
        try:
            await manager.acquire(
                agent_id="b", timeout=0.3,
                config=EnvConfig(servers=["github"], dockerfile_path="D.b"),
            )
        except TimeoutError:
            timed_out = True
        assert timed_out, "PENDING_DESTROY must count toward capacity (backpressure)"

        # Destroyer frees the slot -> acquire now succeeds.
        manager.start_destroyer()
        await asyncio.sleep(0.1)
        env2 = await manager.acquire(
            agent_id="b", timeout=1.0,
            config=EnvConfig(servers=["github"], dockerfile_path="D.b"),
        )
        assert env2.env_id != env.env_id
        await manager.cleanup()

    asyncio.run(scenario())


class FailDestroyProvisioner(FakeProvisioner):
    """Provisioner whose destroy() always fails (simulates a down daemon)."""

    async def destroy(self, env_id: str) -> bool:
        self.destroyed.append(env_id)
        return False


def test_reaper_sweeps_abandoned_error_env():
    """If docker rm keeps failing, the env lingers as ERROR and counts against
    capacity. The reaper must force-drop it so the pool self-heals instead of
    slowly clogging."""
    async def scenario():
        provisioner = FailDestroyProvisioner()
        manager = EnvPoolManager(
            provisioner=provisioner,
            max_pool_size=2,
            auto_scale=True,
            acquisition_timeout=1.0,
            reuse_policy="destroy",
        )
        env = await manager.acquire(
            agent_id="a", timeout=1.0, config=EnvConfig(servers=["github"]),
        )
        # destroy fails -> env lingers as ERROR, NOT popped.
        await manager.destroy(env.env_id)
        assert manager.get_stats().total_envs == 1
        assert env.env_id in manager._envs  # pylint: disable=protected-access

        reaped = await manager._reap_abandoned_envs()  # pylint: disable=protected-access

        assert reaped == 1
        assert manager.get_stats().total_envs == 0
        assert env.env_id not in manager._envs  # pylint: disable=protected-access

    asyncio.run(scenario())


class SlowProvisioner(FakeProvisioner):
    """Provisioner whose create() sleeps, tracking peak concurrent creates."""

    def __init__(self, delay: float):
        super().__init__()
        self.delay = delay
        self._concurrent = 0
        self.max_concurrent = 0

    async def create(self, env_id: str, config: EnvConfig) -> EnvInfo:
        self._concurrent += 1
        self.max_concurrent = max(self.max_concurrent, self._concurrent)
        try:
            await asyncio.sleep(self.delay)
            return await super().create(env_id, config)
        finally:
            self._concurrent -= 1


def test_concurrent_acquire_provisions_in_parallel_bounded_by_semaphore():
    """Per-task images (no reuse): concurrent acquisitions must create in
    parallel (not serialize behind one slow create), bounded by the semaphore,
    and never exceed max_pool_size. This is the core fix for R2E cold-start."""
    async def scenario():
        provisioner = SlowProvisioner(delay=0.1)
        manager = EnvPoolManager(
            provisioner=provisioner,
            max_pool_size=8,
            auto_scale=True,
            acquisition_timeout=10.0,
            provision_concurrency=4,
        )
        # Distinct dockerfile per agent => no env is compatible with another,
        # so every acquire must provision its own (mirrors R2E per-task images).
        configs = [
            EnvConfig(servers=["github"], dockerfile_path=f"Dockerfile.task{i}")
            for i in range(8)
        ]

        start = time.monotonic()
        results = await asyncio.gather(*[
            manager.acquire(agent_id=f"agent-{i}", timeout=10.0, config=configs[i])
            for i in range(8)
        ])
        elapsed = time.monotonic() - start

        # Each agent got a distinct env.
        assert len({e.env_id for e in results}) == 8
        # Concurrency was bounded by the semaphore...
        assert provisioner.max_concurrent <= 4
        # ...but creates actually overlapped (not serialized one-at-a-time).
        assert provisioner.max_concurrent >= 2
        # 8 creates x 0.1s at concurrency 4 ~= 0.2s; serial would be 0.8s.
        assert elapsed < 0.6, f"too slow ({elapsed:.2f}s); creates serialized?"
        # No over-provisioning past the pool cap.
        assert manager.get_stats().total_envs == 8

    asyncio.run(scenario())


def test_provision_never_exceeds_max_pool_size_under_concurrency():
    """Concurrent provisions must atomically respect max_pool_size (no race
    where many pass the capacity check before any registers)."""
    async def scenario():
        provisioner = SlowProvisioner(delay=0.05)
        manager = EnvPoolManager(
            provisioner=provisioner,
            max_pool_size=5,
            auto_scale=True,
            acquisition_timeout=0.5,
            provision_concurrency=16,
        )
        # 12 acquisitions, each a distinct dockerfile, but pool caps at 5.
        configs = [
            EnvConfig(servers=["github"], dockerfile_path=f"Dockerfile.task{i}")
            for i in range(12)
        ]
        results = await asyncio.gather(*[
            manager.acquire(agent_id=f"agent-{i}", timeout=0.5, config=configs[i])
            for i in range(12)
        ], return_exceptions=True)

        # Pool never exceeded its cap regardless of how many acquired/timed out.
        assert manager.get_stats().total_envs <= 5
        assert len(manager._envs) <= 5  # pylint: disable=protected-access
        # The ones that succeeded got real envs; the rest timed out (capacity).
        succeeded = [r for r in results if isinstance(r, EnvInfo)]
        assert 1 <= len(succeeded) <= 5

    asyncio.run(scenario())


def test_acquire_waits_for_release_after_autoprovision_failure():
    async def scenario():
        provisioner = FlakyProvisioner(fail_after=1)
        manager = EnvPoolManager(
            provisioner=provisioner,
            max_pool_size=2,
            auto_scale=True,
            acquisition_timeout=1.0,
        )
        config = EnvConfig(servers=["github"])
        await manager.provision(
            num_envs=1,
            config=config,
            parallel=False,
            reuse_existing=False,
        )
        first = await manager.acquire(
            agent_id="agent-first",
            timeout=1.0,
            config=config,
        )

        acquire_task = asyncio.create_task(manager.acquire(
            agent_id="agent-second",
            timeout=1.0,
            config=config,
        ))
        await asyncio.sleep(0.05)
        assert not acquire_task.done()

        await manager.release(first.env_id)
        second = await acquire_task

        assert second.env_id == first.env_id
        assert second.assigned_agent == "agent-second"
        assert len(provisioner.created_configs) == 1

    asyncio.run(scenario())
