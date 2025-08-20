"""
API endpoints for tasks.
"""
import os
import datetime
from typing import Optional

import psycopg
import sqlalchemy
from fastapi import APIRouter, Depends, HTTPException, Header
from pydantic import BaseModel, Field, SkipValidation
from sqlalchemy.ext.asyncio import AsyncConnection
from mcpuniverse.app.db.database import get_connection
from mcpuniverse.app.db.sqlc.benchmark import AsyncQuerier as BenchmarkAsyncQuerier
from mcpuniverse.app.db.sqlc.task import (
    AsyncQuerier as TaskAsyncQuerier,
    CreateTaskParams,
    UpdateTaskParams
)
from mcpuniverse.app.db.sqlc.released_task import AsyncQuerier as ReleasedTaskQuerier
from mcpuniverse.app.utils.limiter import RateLimiter

router = APIRouter()


class CreateTaskRequest(BaseModel):
    """Request schema for creating a new task."""
    benchmark_name: str = Field(description="benchmark name", min_length=1)
    name: str = Field(description="task name", min_length=1)
    category: str = Field(default="", description="task category")
    question: str = Field(default="", description="task main question")
    config: str = Field(default="", description="task configuration")
    is_public: bool = Field(default=True, description="whether task is public")


class CreateTaskResponse(BaseModel):
    """Response schema for creating a new task."""
    benchmark_name: str = Field(description="benchmark name", min_length=1)
    name: str = Field(description="task name", min_length=1)


class GetTaskResponse(BaseModel):
    """Response schema for querying task information."""
    benchmark_name: str = Field(description="benchmark name")
    name: str = Field(description="task name")
    category: str = Field(default="", description="task category")
    question: str = Field(default="", description="task main question")
    config: str = Field(default="", description="task configuration")
    is_public: bool = Field(default=True, description="whether task is public")
    created_at: SkipValidation[datetime.datetime] = Field(description="created time")
    updated_at: SkipValidation[datetime.datetime] = Field(description="updated time")


class UpdateTaskRequest(BaseModel):
    """Request schema for updating task information."""
    benchmark_name: str = Field(description="benchmark name")
    name: str = Field(description="task name")
    category: str = Field(default=None, description="task category")
    question: str = Field(default=None, description="task main question")
    config: str = Field(default=None, description="task configuration")
    is_public: bool = Field(default=None, description="whether task is public")


class UpdateTaskResponse(BaseModel):
    """Response schema for updating task information."""
    benchmark_name: str = Field(description="benchmark name")
    name: str = Field(description="task name")


class GetReleasedTaskResponse(BaseModel):
    """Response schema for querying released task information."""
    benchmark_id: int = Field(description="benchmark id")
    name: str = Field(description="task name")
    tag: str = Field(description="task name")
    category: str = Field(default="", description="task category")
    question: str = Field(default="", description="task main question")
    config: str = Field(default="", description="task configuration")
    created_at: SkipValidation[datetime.datetime] = Field(description="created time")


@router.post(
    "/internal/task/create",
    response_model=CreateTaskResponse,
    dependencies=[Depends(RateLimiter(rate=os.environ["FORMATTED_RATE_BENCHMARK"], identifier_type="uid"))]
)
async def create_task(
        request: CreateTaskRequest,
        conn: AsyncConnection = Depends(get_connection),
        user_id: Optional[str] = Header(None, alias="x-user-id")
):
    """
    Create a new task.
    """
    if not user_id:
        raise HTTPException(status_code=400, detail="Missing user ID")
    querier = BenchmarkAsyncQuerier(conn)
    benchmark_id = await querier.get_benchmark_id(owner_id=int(user_id), name=request.benchmark_name)
    if benchmark_id is None:
        raise HTTPException(status_code=404, detail="Benchmark not found")

    try:
        querier = TaskAsyncQuerier(conn)
        task = await querier.create_task(CreateTaskParams(
            benchmark_id=benchmark_id,
            name=request.name,
            category=request.category,
            question=request.question,
            data=request.config,
            is_public=request.is_public
        ))
        return CreateTaskResponse(benchmark_name=request.benchmark_name, name=task.name)
    except sqlalchemy.exc.IntegrityError as e:
        if isinstance(e.orig, psycopg.errors.UniqueViolation):
            raise HTTPException(status_code=409, detail="Task already exists") from e


@router.get(
    "/internal/task/get",
    response_model=GetTaskResponse,
    dependencies=[Depends(RateLimiter(rate=os.environ["FORMATTED_RATE_BENCHMARK"], identifier_type="uid"))]
)
async def get_task(
        benchmark_name: str,
        name: str,
        conn: AsyncConnection = Depends(get_connection),
        user_id: Optional[str] = Header(None, alias="x-user-id")
):
    """
    Query task information.
    """
    if not user_id:
        raise HTTPException(status_code=400, detail="Missing user ID")
    querier = BenchmarkAsyncQuerier(conn)
    benchmark_id = await querier.get_benchmark_id(owner_id=int(user_id), name=benchmark_name)
    if benchmark_id is None:
        raise HTTPException(status_code=404, detail="Benchmark not found")

    querier = TaskAsyncQuerier(conn)
    task = await querier.get_task_by_name(benchmark_id=benchmark_id, name=name)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    return GetTaskResponse(
        benchmark_name=benchmark_name,
        name=name,
        category=task.category,
        question=task.question,
        config=task.data,
        is_public=task.is_public,
        created_at=task.created_at,
        updated_at=task.updated_at
    )


@router.post(
    "/internal/task/update",
    response_model=UpdateTaskResponse,
    dependencies=[Depends(RateLimiter(rate=os.environ["FORMATTED_RATE_BENCHMARK"], identifier_type="uid"))]
)
async def update_task(
        request: UpdateTaskRequest,
        conn: AsyncConnection = Depends(get_connection),
        user_id: Optional[str] = Header(None, alias="x-user-id")
):
    """
    Update task information.
    """
    if not user_id:
        raise HTTPException(status_code=400, detail="Missing user ID")
    querier = BenchmarkAsyncQuerier(conn)
    benchmark_id = await querier.get_benchmark_id(owner_id=int(user_id), name=request.benchmark_name)
    if benchmark_id is None:
        raise HTTPException(status_code=404, detail="Benchmark not found")

    querier = TaskAsyncQuerier(conn)
    task = await querier.update_task(UpdateTaskParams(
        benchmark_id=benchmark_id,
        name=request.name,
        category=request.category,
        question=request.question,
        data=request.config,
        is_public=request.is_public,
        updated_at=datetime.datetime.now(datetime.timezone.utc)
    ))
    if not task:
        raise HTTPException(status_code=404, detail="Task update failed")
    return UpdateTaskResponse(benchmark_name=request.benchmark_name, name=task.name)


@router.post(
    "/internal/task/delete",
    dependencies=[Depends(RateLimiter(rate=os.environ["FORMATTED_RATE_BENCHMARK"], identifier_type="uid"))]
)
async def delete_task(
        benchmark_name: str,
        name: str,
        conn: AsyncConnection = Depends(get_connection),
        user_id: Optional[str] = Header(None, alias="x-user-id")
):
    """
    Delete a created task.
    """
    if not user_id:
        raise HTTPException(status_code=400, detail="Missing user ID")
    querier = BenchmarkAsyncQuerier(conn)
    benchmark_id = await querier.get_benchmark_id(owner_id=int(user_id), name=benchmark_name)
    if benchmark_id is None:
        raise HTTPException(status_code=404, detail="Benchmark not found")

    querier = TaskAsyncQuerier(conn)
    task_id = await querier.get_task_id(benchmark_id=benchmark_id, name=name)
    if task_id is None:
        raise HTTPException(status_code=404, detail="Task not found")
    await querier.delete_task(benchmark_id=benchmark_id, name=name)
    return {"status": "ok"}


@router.get(
    "/task/get_release",
    response_model=GetReleasedTaskResponse,
    dependencies=[Depends(RateLimiter(rate=os.environ["FORMATTED_RATE_PUBLIC"], identifier_type="uid"))]
)
async def get_released_task(
        benchmark_id: int,
        name: str,
        tag: str,
        conn: AsyncConnection = Depends(get_connection),
        user_permission: Optional[str] = Header(None, alias="x-user-permission")
):
    """
    Query released task information.
    """
    querier = ReleasedTaskQuerier(conn)
    task = await querier.get_released_task_by_name_and_tag(
        benchmark_id=benchmark_id,
        name=name,
        tag=tag
    )
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    if user_permission not in ["internal", "admin"] and not task.is_public:
        raise HTTPException(status_code=401, detail="Permission denied")
    return GetReleasedTaskResponse(
        benchmark_id=benchmark_id,
        name=name,
        tag=tag,
        category=task.category,
        question=task.question,
        config=task.data,
        created_at=task.created_at
    )
