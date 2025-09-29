"""
Celery task registry.
"""
from .celery_config import WORKER, AGENT_COLLECTION_CONFIG_FILE
from .task import AgentTask

WORKER.register_task(AgentTask(agent_collection_config=AGENT_COLLECTION_CONFIG_FILE))
