"""
API endpoints for benchmarks.
"""
import os
import datetime
from typing import Optional, List, Tuple

import psycopg
import sqlalchemy
from fastapi import APIRouter, Depends, HTTPException, Header
from pydantic import BaseModel, Field, SkipValidation
from sqlalchemy.ext.asyncio import AsyncConnection
from mcpuniverse.app.db.database import get_connection
from mcpuniverse.app.db.sqlc.benchmark import AsyncQuerier
from mcpuniverse.app.db.sqlc.task import AsyncQuerier as TaskQuerier
from mcpuniverse.app.db.sqlc.released_benchmark import AsyncQuerier as ReleasedBenchmarkQuerier
from mcpuniverse.app.db.sqlc.released_task import AsyncQuerier as ReleasedTaskQuerier, CreateReleasedTaskParams
from mcpuniverse.app.db.sqlc.user import AsyncQuerier as UserQuerier
from mcpuniverse.app.utils.limiter import RateLimiter

router = APIRouter()


class CreateBenchmarkRequest(BaseModel):
    """Request schema for creating a new benchmark."""
    name: str = Field(description="benchmark name", min_length=1)
    description: str = Field(default="", description="benchmark description")


class CreateBenchmarkResponse(BaseModel):
    """Response schema for creating a new benchmark."""
    name: str = Field(description="benchmark name")


class GetBenchmarkResponse(BaseModel):
    """Response schema for querying benchmark information."""
    name: str = Field(description="benchmark name")
    description: str = Field(description="benchmark description")
    created_at: SkipValidation[datetime.datetime] = Field(description="created time")
    updated_at: SkipValidation[datetime.datetime] = Field(description="updated time")


class UpdateBenchmarkRequest(BaseModel):
    """Request schema for updating benchmark information."""
    name: str = Field(description="benchmark name", min_length=1)
    description: str = Field(default=None, description="benchmark description")


class UpdateBenchmarkResponse(BaseModel):
    """Response schema for updating benchmark information."""
    name: str = Field(description="benchmark name")


class CreateReleasedBenchmarkRequest(BaseModel):
    """Request schema for creating a released benchmark."""
    owner_name: str = Field(description="owner name")
    name: str = Field(description="benchmark name", min_length=1)
    tag: str = Field(description="release tag")


class CreateReleasedBenchmarkResponse(BaseModel):
    """Response schema for creating a released benchmark."""
    id: int = Field(description="benchmark ID")
    owner_name: str = Field(description="owner name")
    name: str = Field(description="benchmark name")
    tag: str = Field(description="release tag")


class GetReleasedBenchmarkResponse(BaseModel):
    """Response schema for querying released benchmark information."""
    id: int = Field(description="released benchmark ID")
    owner_name: str = Field(description="owner name")
    name: str = Field(description="released benchmark name")
    description: str = Field(description="released benchmark description")
    created_at: SkipValidation[datetime.datetime] = Field(description="created time")
    tasks: List[str] = Field(default_factory=list, description="benchmark tasks")


class ListReleasedBenchmarkRequest(BaseModel):
    """Request schema for listing released benchmarks."""
    limit: int = Field(description="limit", gt=0, le=100)
    offset: int = Field(default=0, description="offset", ge=0)


class ListReleasedBenchmarkResponse(BaseModel):
    """Response schema for listing released benchmarks."""
    benchmarks: List[Tuple[int, str]] = Field(description="benchmark owners and names")


@router.post(
    "/internal/benchmark/create",
    response_model=CreateBenchmarkResponse,
    dependencies=[Depends(RateLimiter(rate=os.environ["FORMATTED_RATE_BENCHMARK"], identifier_type="uid"))]
)
async def create_benchmark(
        request: CreateBenchmarkRequest,
        conn: AsyncConnection = Depends(get_connection),
        user_id: Optional[str] = Header(None, alias="x-user-id")
):
    """
    Create a new benchmark.
    """
    if not user_id:
        raise HTTPException(status_code=400, detail="Missing user ID")
    querier = AsyncQuerier(conn)
    try:
        benchmark = await querier.create_benchmark(
            owner_id=int(user_id),
            name=request.name,
            description=request.description
        )
        return CreateBenchmarkResponse(name=benchmark.name)
    except sqlalchemy.exc.IntegrityError as e:
        if isinstance(e.orig, psycopg.errors.UniqueViolation):
            raise HTTPException(status_code=409, detail="Benchmark already exists") from e


@router.get(
    "/internal/benchmark/get",
    response_model=GetBenchmarkResponse,
    dependencies=[Depends(RateLimiter(rate=os.environ["FORMATTED_RATE_BENCHMARK"], identifier_type="uid"))]
)
async def get_benchmark(
        name: str,
        conn: AsyncConnection = Depends(get_connection),
        user_id: Optional[str] = Header(None, alias="x-user-id")
):
    """
    Query benchmark information.
    """
    if not user_id:
        raise HTTPException(status_code=400, detail="Missing user ID")
    querier = AsyncQuerier(conn)
    benchmark = await querier.get_benchmark_by_name(
        owner_id=int(user_id),
        name=name
    )
    if not benchmark:
        raise HTTPException(status_code=404, detail="Benchmark not found")
    return GetBenchmarkResponse(
        name=benchmark.name,
        description=benchmark.description,
        created_at=benchmark.created_at,
        updated_at=benchmark.updated_at
    )


@router.post(
    "/internal/benchmark/update",
    response_model=UpdateBenchmarkResponse,
    dependencies=[Depends(RateLimiter(rate=os.environ["FORMATTED_RATE_BENCHMARK"], identifier_type="uid"))]
)
async def update_benchmark(
        request: UpdateBenchmarkRequest,
        conn: AsyncConnection = Depends(get_connection),
        user_id: Optional[str] = Header(None, alias="x-user-id")
):
    """
    Update benchmark information.
    """
    if not user_id:
        raise HTTPException(status_code=400, detail="Missing user ID")
    querier = AsyncQuerier(conn)
    benchmark = await querier.update_benchmark(
        owner_id=int(user_id),
        name=request.name,
        description=request.description,
        updated_at=datetime.datetime.now(datetime.timezone.utc)
    )
    if not benchmark:
        raise HTTPException(status_code=404, detail="Benchmark update failed")
    return UpdateBenchmarkResponse(name=benchmark.name)


@router.post(
    "/admin/benchmark/create_release",
    response_model=CreateReleasedBenchmarkResponse,
    dependencies=[Depends(RateLimiter(rate=os.environ["FORMATTED_RATE_BENCHMARK"], identifier_type="uid"))]
)
async def create_released_benchmark(
        request: CreateReleasedBenchmarkRequest,
        conn: AsyncConnection = Depends(get_connection)
):
    """
    Create a released benchmark.
    """
    querier = UserQuerier(conn)
    user = await querier.get_user_by_name(username=request.owner_name)
    if not user:
        raise HTTPException(status_code=404, detail="Owner not found")

    querier = AsyncQuerier(conn)
    benchmark = await querier.get_benchmark_by_name(
        owner_id=user.id,
        name=request.name
    )
    if not benchmark:
        raise HTTPException(status_code=404, detail="Benchmark not found")

    try:
        # Create released benchmark
        querier = ReleasedBenchmarkQuerier(conn)
        release = await querier.create_released_benchmark(
            owner_id=user.id,
            name=request.name,
            tag=request.tag,
            description=benchmark.description
        )
        response = CreateReleasedBenchmarkResponse(
            id=release.id,
            owner_name=user.username,
            name=release.name,
            tag=release.tag
        )
        # Create released tasks in this benchmark
        querier = TaskQuerier(conn)
        task_querier = ReleasedTaskQuerier(conn)
        async for task_name in querier.get_task_names_in_benchmark(benchmark_id=benchmark.id):
            task = await querier.get_task_by_name(benchmark_id=benchmark.id, name=task_name)
            await task_querier.create_released_task(CreateReleasedTaskParams(
                benchmark_id=release.id,
                name=task.name,
                tag=release.tag,
                category=task.category,
                question=task.question,
                data=task.data,
                is_public=task.is_public
            ))
        return response
    except sqlalchemy.exc.IntegrityError as e:
        if isinstance(e.orig, psycopg.errors.UniqueViolation):
            raise HTTPException(status_code=409, detail="Benchmark release already exists") from e


@router.get(
    "/benchmark/get_release",
    response_model=GetReleasedBenchmarkResponse,
    dependencies=[Depends(RateLimiter(rate=os.environ["FORMATTED_RATE_PUBLIC"], identifier_type="uid"))]
)
async def get_released_benchmark(
        owner_name: str,
        name: str,
        tag: str,
        conn: AsyncConnection = Depends(get_connection)
):
    """
    Query benchmark information.
    """
    querier = UserQuerier(conn)
    user = await querier.get_user_by_name(username=owner_name)
    if not user:
        raise HTTPException(status_code=404, detail="Owner not found")

    querier = ReleasedBenchmarkQuerier(conn)
    benchmark = await querier.get_released_benchmark_by_name_and_tag(
        owner_id=user.id,
        name=name,
        tag=tag
    )
    if not benchmark:
        raise HTTPException(status_code=404, detail="Benchmark release not found")

    querier = ReleasedTaskQuerier(conn)
    tasks = [name async for name in querier.get_released_task_names(benchmark_id=benchmark.id)]
    return GetReleasedBenchmarkResponse(
        id=benchmark.id,
        owner_name=user.username,
        name=benchmark.name,
        description=benchmark.description,
        created_at=benchmark.created_at,
        tasks=tasks
    )


@router.post(
    "/benchmark/list_release",
    response_model=ListReleasedBenchmarkResponse,
    dependencies=[Depends(RateLimiter(rate=os.environ["FORMATTED_RATE_PUBLIC"], identifier_type="uid"))]
)
async def list_released_benchmark(
        request: ListReleasedBenchmarkRequest,
        conn: AsyncConnection = Depends(get_connection)
):
    """
    List released benchmarks.
    """
    querier = ReleasedBenchmarkQuerier(conn)
    benchmarks = [(r.owner_id, r.name) async for r in querier.list_released_benchmarks(
        limit=request.limit,
        offset=request.offset
    )]
    return ListReleasedBenchmarkResponse(benchmarks=benchmarks)
