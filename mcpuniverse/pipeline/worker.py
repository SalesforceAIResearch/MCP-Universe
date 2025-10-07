"""
Celery task registry.
"""
import os
from .celery_config import WORKER
from .task import AgentTask

AGENT_COLLECTION_CONFIG_FILE = os.environ["AGENT_COLLECTION_CONFIG_FILE"]
WORKER.register_task(AgentTask(agent_collection_config=AGENT_COLLECTION_CONFIG_FILE))
