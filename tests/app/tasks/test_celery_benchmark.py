import os
import unittest
import pytest
import time
from celery import states
from mcpuniverse.app.tasks import TASK_BENCHMARK
from mcpuniverse.app.tasks.celery_config import send_task


class TestCelery(unittest.TestCase):

    @pytest.mark.skip
    def test(self):
        folder = os.path.dirname(os.path.realpath(__file__))
        task_path = os.path.join(folder, "../../data/task/weather_task.json")
        task = send_task(task=TASK_BENCHMARK, kwargs={
            "job_id": "",
            "project_id": "test",
            "config": """
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
""",
            "agent_name": "ReAct-agent",
            "tasks": [task_path]
        })
        print(task.id)
        while True:
            status, result = task.status, task.result
            print(status, result)
            time.sleep(1)
            if status == states.SUCCESS:
                break


if __name__ == "__main__":
    unittest.main()
