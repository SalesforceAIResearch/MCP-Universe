"""
API endpoints for benchmark jobs.
"""
import json
import os
import uuid
import datetime
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Header
from pydantic import BaseModel, Field, SkipValidation
from sqlalchemy.ext.asyncio import AsyncConnection

from mcpuniverse.common.context import Context
from mcpuniverse.benchmark.task import Task
from mcpuniverse.app.db.database import get_connection
from mcpuniverse.app.db.sqlc.benchmark_job import AsyncQuerier, UpdateBenchmarkJobParams
from mcpuniverse.app.db.sqlc.released_project import AsyncQuerier as ReleasedProjectQuerier
from mcpuniverse.app.db.sqlc.released_benchmark import AsyncQuerier as ReleasedBenchmarkQuerier
from mcpuniverse.app.db.sqlc.released_task import AsyncQuerier as ReleasedTaskQuerier
from mcpuniverse.app.utils.limiter import RateLimiter
from mcpuniverse.app.core.engine import app_engine
from mcpuniverse.app.tasks import TASK_BENCHMARK
from mcpuniverse.app.tasks.celery_config import send_task

router = APIRouter()


class CreateBenchmarkJobRequest(BaseModel):
    """Request schema for creating a new benchmark job."""
    project_name: str = Field(description="project name", min_length=1)
    project_tag: str = Field(description="project tag", min_length=1)
    benchmark_id: int = Field(description="benchmark ID")
    context: Optional[Context] = Field(default=Context(), description="request context")


class CreateBenchmarkJobResponse(BaseModel):
    """Response schema for creating a new benchmark job."""
    job_id: str = Field(description="job ID")


class GetBenchmarkJobResponse(BaseModel):
    """Response schema for querying job information."""
    job_id: str = Field(description="job ID")
    project_name: str = Field(description="project name")
    project_tag: str = Field(description="project tag")
    benchmark_id: int = Field(description="benchmark ID")
    status: SkipValidation[str] = Field(description="job status")
    progress: SkipValidation[int] = Field(description="job progress")
    results: SkipValidation[str] = Field(description="job results")
    score: SkipValidation[float] = Field(description="metric score")
    celery_id: SkipValidation[str] = Field(description="celery task ID")
    created_at: SkipValidation[datetime.datetime] = Field(description="created time")
    updated_at: SkipValidation[datetime.datetime] = Field(description="updated time")


@router.post(
    "/benchmark_job/create",
    response_model=CreateBenchmarkJobResponse,
    dependencies=[Depends(RateLimiter(rate=os.environ["FORMATTED_RATE_JOB"], identifier_type="uid"))]
)
async def create_benchmark_job(
        request: CreateBenchmarkJobRequest,
        conn: AsyncConnection = Depends(get_connection),
        user_id: Optional[str] = Header(None, alias="x-user-id")
):
    """
    Create a new benchmark job.
    """
    if not user_id:
        raise HTTPException(status_code=400, detail="Missing user ID")
    querier = ReleasedProjectQuerier(conn)
    project = await querier.get_released_project_by_name_and_tag(
        owner_id=int(user_id),
        name=request.project_name,
        tag=request.project_tag
    )
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    flag, reason = app_engine.check_config(config=project.configuration, context=request.context)
    if not flag:
        raise HTTPException(status_code=400, detail=reason)

    querier = ReleasedBenchmarkQuerier(conn)
    benchmark = await querier.get_released_benchmark_by_id(id=int(request.benchmark_id))
    if not benchmark:
        raise HTTPException(status_code=404, detail="Benchmark not found")

    tasks = []
    querier = ReleasedTaskQuerier(conn)
    async for task_config in querier.get_released_task_configs(benchmark_id=benchmark.id):
        try:
            Task(config=json.loads(task_config), context=request.context)
            tasks.append(task_config)
        except Exception as e:
            raise HTTPException(status_code=404, detail="Failed to parse task configuration") from e

    querier = AsyncQuerier(conn)
    job = await querier.create_benchmark_job(
        job_id=str(uuid.uuid4()),
        owner_id=int(user_id),
        benchmark_id=benchmark.id,
        project_id=project.id
    )
    if not job:
        raise HTTPException(status_code=409, detail="Failed to create benchmark job")

    try:
        param = {
            "job_id": job.job_id,
            "project_id": project.id,
            "config": project.configuration,
            "agent_name": "",
            "tasks": tasks,
            "context": request.context.model_dump(mode="json")
        }
        task = send_task(task=TASK_BENCHMARK, kwargs=param)
    except Exception as e:
        raise HTTPException(status_code=500, detail="Failed to submit benchmark job") from e

    querier = AsyncQuerier(conn)
    job = await querier.update_benchmark_job(UpdateBenchmarkJobParams(
        job_id=job.job_id, status=None, progress=None,
        results=None, score=None, celery_id=task.id,
        updated_at=datetime.datetime.now(datetime.timezone.utc)
    ))
    if not job:
        raise HTTPException(status_code=500, detail="Failed to update benchmark job")
    return CreateBenchmarkJobResponse(job_id=job.job_id)


@router.get(
    "/benchmark_job/get",
    response_model=GetBenchmarkJobResponse,
    dependencies=[Depends(RateLimiter(rate=os.environ["FORMATTED_RATE_PUBLIC"], identifier_type="uid"))]
)
async def get_benchmark_job(
        job_id: str,
        conn: AsyncConnection = Depends(get_connection)
):
    """
    Query released project information.
    """
    querier = AsyncQuerier(conn)
    job = await querier.get_benchmark_job_by_id(job_id=job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Benchmark job not found")

    project_id = job.project_id
    querier = ReleasedProjectQuerier(conn)
    project = await querier.get_released_project_by_id(id=project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project in the job not found")

    return GetBenchmarkJobResponse(
        job_id=job.job_id,
        project_name=project.name,
        project_tag=project.tag,
        benchmark_id=job.benchmark_id,
        status=job.status,
        progress=job.progress,
        results=job.results,
        score=job.score,
        celery_id=job.celery_id,
        created_at=job.created_at,
        updated_at=job.updated_at
    )
