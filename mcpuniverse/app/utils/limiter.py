"""
Request rate limiter for FastAPI.
"""
# pylint: disable=unused-argument
from math import ceil
from typing import Optional, Callable

import redis
from fastapi import HTTPException
from starlette.requests import Request
from starlette.responses import Response
from mcpuniverse.app.utils.redis import new_redis_client


def http_callback(request: Request, response: Response, expire: int):
    """Default callback if there are too many requests."""
    expire = ceil(expire / 1000)
    raise HTTPException(
        status_code=429, detail="Too Many Requests", headers={"Retry-After": str(expire)}
    )


def ip_identifier(request: Request):
    """
    Get client IP from X-Forwarded-For:
    https://cloud.google.com/load-balancing/docs/https#x-forwarded-for_header
    """
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        ips = forwarded.split(",")
        num_ips = len(ips)
        ip = request.client.host if num_ips < 2 else ips[num_ips - 2].strip()
    else:
        ip = request.client.host
    return f"{ip}:{request.scope['path']}"


def uid_identifier(request: Request):
    """
    Get the user ID from the request header.
    """
    uid = request.headers.get("x-user-id")
    if not uid:
        raise HTTPException(status_code=401, detail="No user ID")
    return f"{uid}:{request.scope['path']}"


class RateLimiter:
    """
    The rate limiter.
    """
    redis_client: redis.Redis = None
    prefix: str = "rate-limiter"
    skip: bool = False

    @classmethod
    def init(
            cls,
            host: str,
            port: int = 5379,
            password: Optional[str] = None,
            prefix: str = "rate-limiter"
    ):
        """
        Set up the rate limiter class.
        """
        cls.redis_client = new_redis_client(host=host, port=port, password=password)
        cls.prefix = prefix

    @classmethod
    def close(cls):
        """
        Close the redis connection.
        """
        cls.redis_client.close()

    def __init__(
            self,
            rate: str,
            identifier_type: str = "ip"
    ):
        identifier_type = identifier_type.lower()
        assert identifier_type in ["ip", "uid"], "`identifier_type` must be `ip` or `uid`"

        self.rate = rate
        if rate:
            values = rate.split("-")
            if len(values) != 2:
                raise ValueError("Wrong rate limit format")
            times = int(values[0])
            formats = {"s": (1, 0, 0), "m": (0, 1, 0), "h": (0, 0, 1), "d": (0, 0, 24)}
            seconds, minutes, hours = formats.get(values[1].lower(), (-1, -1, -1))
            if seconds < 0:
                raise ValueError("Wrong rate limit format")
        else:
            times, seconds, minutes, hours = 0, 0, 0, 0

        self._initialize(
            times=times,
            seconds=seconds,
            minutes=minutes,
            hours=hours,
            identifier=ip_identifier if identifier_type == "ip" else uid_identifier,
            callback=http_callback
        )

    def _initialize(
            self,
            times: int = 1,
            milliseconds: Optional[int] = 0,
            seconds: Optional[int] = 0,
            minutes: Optional[int] = 0,
            hours: Optional[int] = 0,
            identifier: Optional[Callable] = ip_identifier,
            callback: Optional[Callable] = http_callback,
    ):
        self.times = times
        self.milliseconds = milliseconds + 1000 * seconds + 60000 * minutes + 3600000 * hours
        self.identifier = identifier
        self.callback = callback

    def _check(self, key):
        """Check if a key exceeds the limit."""
        client = RateLimiter.redis_client
        count = client.get(key)
        count = 0 if count is None else int(count)
        if count > 0:
            if count + 1 > self.times:
                return client.pttl(key)
            client.incr(key)
        else:
            client.set(key, 1, px=self.milliseconds)
        return 0

    async def __call__(self, request: Request, response: Response):
        """Execute the rate limit checker."""
        if RateLimiter.skip or self.rate == "":
            return
        route_index, dep_index = 0, 0
        for i, route in enumerate(request.app.routes):
            if route.path == request.scope["path"] and request.method in route.methods:
                route_index = i
                for j, dependency in enumerate(route.dependencies):
                    if self is dependency.dependency:
                        dep_index = j
                        break

        rate_key = self.identifier(request)
        key = f"{RateLimiter.prefix}:{rate_key}:{route_index}:{dep_index}"
        expire = self._check(key)
        if expire != 0:
            return self.callback(request, response, expire)
