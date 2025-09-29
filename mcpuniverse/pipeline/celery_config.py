"""
Celery App Configuration.
"""
# pylint: disable=unused-argument
import os
from celery import Celery, signals
from dotenv import load_dotenv

load_dotenv()

BROKER = f"redis://{os.environ['REDIS_HOST']}:{os.environ['REDIS_PORT']}/0"
RESULT_BACKEND = f"redis://{os.environ['REDIS_HOST']}:{os.environ['REDIS_PORT']}/0"

WORKER = Celery("celery_app", broker=BROKER)
WORKER.conf.update(
    {
        "result_backend": RESULT_BACKEND,
        "task_track_started": True,
        "worker_prefetch_multiplier": 1,
        "worker_cancel_long_running_tasks_on_connection_loss": True,
        "task_soft_time_limit": 2400,
        "task_time_limit": 3600,
        "broker_connection_retry_on_startup": True,
    }
)


@signals.setup_logging.connect
def setup_celery_logging(**kwargs):
    """Resovle `AttributeError: 'LoggingProxy' object has no attribute 'fileno'`"""


def send_task(task, args=None, kwargs=None, queue=None):
    """
    Provides the task priority level based on message source
    """
    if kwargs is None:
        kwargs = {}
    return WORKER.send_task(task, args=args, kwargs=kwargs, queue=queue)
