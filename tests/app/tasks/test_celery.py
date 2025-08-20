import unittest
import pytest
import time
from celery import states
from mcpuniverse.app.tasks import TASK_ECHO
from mcpuniverse.app.tasks.celery_config import send_task


class TestCelery(unittest.TestCase):

    @pytest.mark.skip
    def test(self):
        task = send_task(task=TASK_ECHO, kwargs={"data": "yes"})
        while True:
            status, result = task.status, task.result
            print(status, result)
            time.sleep(1)
            if status == states.SUCCESS:
                break


if __name__ == "__main__":
    unittest.main()
