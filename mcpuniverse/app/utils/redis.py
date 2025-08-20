"""
Create a redis client.
"""
from typing import Optional
import redis


def new_redis_client(host: str, port: int = 5379, password: Optional[str] = None) -> redis.Redis:
    """
    Create a new redis client.

    Args:
        host (str): The redis host address.
        port (int): The redis host port.
        password (str, optional): The redis password.

    Returns:
        redis.Redis: A redis client.
    """
    client = redis.Redis(host=host, port=port, password=password)
    client.ping()
    return client
