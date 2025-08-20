import os
import unittest
import pytest
import asyncio
from mcpuniverse.app.core.engine import AppEngine
from mcpuniverse.benchmark.task import Task
from mcpuniverse.app.db.database import sessionmanager
from mcpuniverse.app.db.sqlc.user import AsyncQuerier as UserQuerier, models
from mcpuniverse.app.db.sqlc.released_project import AsyncQuerier as ProjectQuerier, CreateReleasedProjectParams
from mcpuniverse.app.db.sqlc.released_benchmark import AsyncQuerier as BenchmarkQuerier
from mcpuniverse.app.db.sqlc.benchmark_job import AsyncQuerier as JobQuerier


class TestEngine(unittest.IsolatedAsyncioTestCase):

    def setUp(self):
        self.engine = AppEngine()

    async def _initialize(self):
        # Create user
        sessionmanager.init(host=os.environ["DB_SOURCE"])
        async with sessionmanager.engine.begin() as conn:
            queries = UserQuerier(conn)
            user = await queries.get_user_by_name(username="abcd")
            if not user:
                user = await queries.create_user(
                    username="abcd",
                    email="abcd@gmail.com",
                    hashed_password="12345",
                    permission=models.UserPerm.DEFAULT
                )
            queries = ProjectQuerier(conn)
            project = await queries.get_released_project_by_name_and_tag(
                owner_id=user.id, name="test", tag="v1")
            if not project:
                project = await queries.create_released_project(CreateReleasedProjectParams(
                    owner_id=user.id,
                    name="test",
                    tag="v1",
                    description="a test project",
                    configuration="{}"
                ))
            queries = BenchmarkQuerier(conn)
            benchmark = await queries.get_released_benchmark_by_name_and_tag(
                owner_id=user.id, name="test", tag="v1")
            if not benchmark:
                benchmark = await queries.create_released_benchmark(
                    owner_id=user.id,
                    name="test",
                    tag="v1",
                    description="a test benchmark"
                )
            queries = JobQuerier(conn)
            job = await queries.get_benchmark_job_by_id(job_id="test")
            if not job:
                await queries.create_benchmark_job(
                    job_id="test",
                    owner_id=user.id,
                    benchmark_id=benchmark.id,
                    project_id=project.id
                )

    @pytest.mark.skip
    async def test_run(self):
        config = """
kind: llm
spec:
  name: llm-1
  type: openai
  config:
    model_name: gpt-4o

---
kind: agent
spec:
  name: ReAct-agent
  type: react
  config:
    llm: llm-1
    instruction: You are an agent for weather forecasting.
    servers:
      - name: weather
        """
        question = "What's the weather in San Francisco now?"

        async def _run(_project_id):
            return await self.engine.run(
                project_id=_project_id,
                config=config,
                agent_name="ReAct-agent",
                question=question
            )

        results = await asyncio.gather(
            *[_run(project_id) for project_id in ["test-1", "test-2"]]
        )
        print("Answer:")
        print(results[0])
        print("LLM:")
        print(self.engine.get_message(
            project_id="test-1",
            component_type="llm",
            component_name="llm-1",
            message_type="response"
        ))
        print("MCP:")
        print(self.engine.get_message(
            project_id="test-1",
            component_type="mcp",
            component_name="weather",
            message_type="response"
        ))

    @pytest.mark.skip
    async def test_run_task(self):
        config = """
kind: llm
spec:
  name: llm-1
  type: openai
  config:
    model_name: gpt-4o

---
kind: agent
spec:
  name: ReAct-agent
  type: react
  config:
    llm: llm-1
    instruction: You are an agent for weather forecasting.
    servers:
      - name: weather
        """
        folder = os.path.dirname(os.path.realpath(__file__))
        task_path = os.path.join(folder, "../../data/task/weather_task.json")
        task = Task(config=task_path)

        await self._initialize()
        results = await self.engine.run_tasks(
            job_id="test",
            project_id="test-task",
            config=config,
            agent_name="ReAct-agent",
            tasks=[task]
        )
        print(results)
        async with sessionmanager.engine.begin() as conn:
            queries = JobQuerier(conn)
            job = await queries.get_benchmark_job_by_id(job_id="test")
            print(job)


if __name__ == "__main__":
    unittest.main()
