"""
The API server.
"""
# pylint: disable=unused-argument,broad-exception-caught
import os
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.exceptions import RequestValidationError
from sqlalchemy.exc import OperationalError
from mcpuniverse.common.logger import get_logger
from mcpuniverse.app.db.database import sessionmanager
from mcpuniverse.app.db.migration import run_migration
from mcpuniverse.app.utils.limiter import RateLimiter

from mcpuniverse.app.api.middleware import AuthMiddleware
from mcpuniverse.app.api.user import router as user_router
from mcpuniverse.app.api.project import router as project_router
from mcpuniverse.app.api.benchmark import router as benchmark_router
from mcpuniverse.app.api.task import router as task_router
from mcpuniverse.app.api.job import router as job_router
from mcpuniverse.app.api.chat import router as chat_router

load_dotenv()
logger = get_logger("Backend")


@asynccontextmanager
async def lifespan(_: FastAPI):
    """
    Function that handles startup and shutdown events.
    To understand more, read https://fastapi.tiangolo.com/advanced/events/
    """
    RateLimiter.init(
        host=os.environ["REDIS_HOST"],
        port=int(os.environ["REDIS_PORT"]),
    )
    yield
    RateLimiter.close()
    await sessionmanager.close()


def init_app(is_test: bool = False):
    """Initialize a FastAPI app."""
    _lifespan = None
    if not is_test:
        try:
            _lifespan = lifespan
            sessionmanager.init(host=os.environ["DB_SOURCE"])
            run_migration()
        except Exception as e:
            logger.fatal("Failed to initialize server: %s", str(e))
    else:
        RateLimiter.skip = True

    _app = FastAPI(title="MCPUniverse", lifespan=_lifespan, docs_url="/api/docs")
    _app.include_router(user_router)
    _app.include_router(project_router)
    _app.include_router(benchmark_router)
    _app.include_router(task_router)
    _app.include_router(job_router)
    _app.include_router(chat_router)
    _app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    if not is_test:
        _app.add_middleware(AuthMiddleware)

    @_app.exception_handler(HTTPException)
    async def http_exception_handler(request: Request, exc: HTTPException):
        """HTTP exception handler."""
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "detail": exc.detail,
                "path": request.url.path
            }
        )

    @_app.exception_handler(RequestValidationError)
    async def validation_exception_handler(request: Request, exc: RequestValidationError):
        return JSONResponse(
            status_code=400,
            content={
                "detail": "Request validation error",
                "path": request.url.path
            }
        )

    @_app.exception_handler(OperationalError)
    async def sqlalchemy_operational_exception_handler(request: Request, exc: OperationalError):
        logger.error("Unexpected error: %s", str(exc))
        return JSONResponse(
            status_code=500,
            content={
                "detail": "An unexpected error occurred",
                "path": request.url.path
            }
        )

    @_app.exception_handler(Exception)
    async def global_exception_handler(request: Request, exc: Exception):
        """Default exception handler."""
        logger.error("Unexpected error: %s", str(exc))
        return JSONResponse(
            status_code=500,
            content={
                "detail": "An unexpected error occurred",
                "path": request.url.path
            }
        )

    return _app
