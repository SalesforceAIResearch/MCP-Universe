"""
Celery task registry.
"""
from .celery_config import WORKER
from .echo import EchoTask
from .benchmark import Benchmark

WORKER.register_task(EchoTask())
WORKER.register_task(Benchmark())
