"""
A simple task for testing purpose.
"""
import time
from celery import Task
from mcpuniverse.common.logger import get_logger


class EchoTask(Task):
    """
    A simple task for testing purpose.
    """
    logger = get_logger(__name__)

    def run(self, *args, **kwargs):
        """Print `echo`"""
        time.sleep(2)
        self.logger.info("Echo")
        return f"echo {kwargs.get('data', '')}"
