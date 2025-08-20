"""
API endpoints for projects.
"""
import os
import datetime
from typing import Optional, List

import psycopg
import sqlalchemy
from fastapi import APIRouter, Depends, HTTPException, Header
from pydantic import BaseModel, Field, SkipValidation
from sqlalchemy.ext.asyncio import AsyncConnection
from mcpuniverse.app.db.database import get_connection
from mcpuniverse.app.db.sqlc.project import AsyncQuerier, UpdateProjectParams
from mcpuniverse.app.db.sqlc.released_project import (
    AsyncQuerier as ReleasedAsyncQuerier,
    CreateReleasedProjectParams
)
from mcpuniverse.app.utils.limiter import RateLimiter

router = APIRouter()


class CreateProjectRequest(BaseModel):
    """Request schema for creating a new project."""
    name: str = Field(description="project name", min_length=1)
    description: str = Field(default="", description="project description")
    configuration: str = Field(default="", description="project configuration")


class CreateProjectResponse(BaseModel):
    """Response schema for creating a new project."""
    name: str = Field(description="project name")


class GetProjectResponse(BaseModel):
    """Response schema for querying project information."""
    name: str = Field(description="project name")
    description: str = Field(description="project description")
    configuration: str = Field(description="project configuration")
    created_at: SkipValidation[datetime.datetime] = Field(description="created time")
    updated_at: SkipValidation[datetime.datetime] = Field(description="updated time")


class UpdateProjectRequest(BaseModel):
    """Request schema for updating project information."""
    name: str = Field(description="project name", min_length=1)
    description: str = Field(default=None, description="project description")
    configuration: str = Field(default=None, description="project configuration")


class UpdateProjectResponse(BaseModel):
    """Response schema for updating project information."""
    name: str = Field(description="project name")


class ListProjectsRequest(BaseModel):
    """Request schema for listing projects."""
    limit: int = Field(description="limit", gt=0, le=100)
    offset: int = Field(default=0, description="offset", ge=0)


class ListProjectResponse(BaseModel):
    """Response schema for listing projects."""
    projects: List[str] = Field(description="project names")


class CreateReleasedProjectRequest(BaseModel):
    """Request schema for creating a released project."""
    name: str = Field(description="project name", min_length=1)
    tag: str = Field(description="release tag")


class CreateReleasedProjectResponse(BaseModel):
    """Response schema for creating a released project."""
    name: str = Field(description="project name")
    tag: str = Field(description="release tag")


class GetReleasedProjectResponse(BaseModel):
    """Response schema for querying released project information."""
    name: str = Field(description="project name")
    tag: str = Field(description="release tag")
    description: str = Field(description="project description")
    configuration: str = Field(description="project configuration")
    created_at: SkipValidation[datetime.datetime] = Field(description="created time")


@router.post(
    "/project/create",
    response_model=CreateProjectResponse,
    dependencies=[Depends(RateLimiter(rate=os.environ["FORMATTED_RATE_PROJECT"], identifier_type="uid"))]
)
async def create_project(
        request: CreateProjectRequest,
        conn: AsyncConnection = Depends(get_connection),
        user_id: Optional[str] = Header(None, alias="x-user-id")
):
    """
    Create a new project.
    """
    if not user_id:
        raise HTTPException(status_code=400, detail="Missing user ID")
    querier = AsyncQuerier(conn)
    try:
        project = await querier.create_project(
            owner_id=int(user_id),
            name=request.name,
            description=request.description,
            configuration=request.configuration
        )
        return CreateProjectResponse(name=project.name)
    except sqlalchemy.exc.IntegrityError as e:
        if isinstance(e.orig, psycopg.errors.UniqueViolation):
            raise HTTPException(status_code=409, detail="Project already exists") from e


@router.get(
    "/project/get",
    response_model=GetProjectResponse,
    dependencies=[Depends(RateLimiter(rate=os.environ["FORMATTED_RATE_PROJECT"], identifier_type="uid"))]
)
async def get_project(
        name: str,
        conn: AsyncConnection = Depends(get_connection),
        user_id: Optional[str] = Header(None, alias="x-user-id")
):
    """
    Query project information.
    """
    if not user_id:
        raise HTTPException(status_code=400, detail="Missing user ID")
    querier = AsyncQuerier(conn)
    project = await querier.get_project_by_name(
        owner_id=int(user_id),
        name=name
    )
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    return GetProjectResponse(
        name=project.name,
        description=project.description,
        configuration=project.configuration,
        created_at=project.created_at,
        updated_at=project.updated_at
    )


@router.post(
    "/project/delete",
    dependencies=[Depends(RateLimiter(rate=os.environ["FORMATTED_RATE_PROJECT"], identifier_type="uid"))]
)
async def delete_project(
        name: str,
        conn: AsyncConnection = Depends(get_connection),
        user_id: Optional[str] = Header(None, alias="x-user-id")
):
    """
    Delete a created project.
    """
    if not user_id:
        raise HTTPException(status_code=400, detail="Missing user ID")
    querier = AsyncQuerier(conn)
    project_id = await querier.get_project_id(owner_id=int(user_id), name=name)
    if project_id is None:
        raise HTTPException(status_code=404, detail="Project not found")
    await querier.delete_project(owner_id=int(user_id), name=name)
    return {"status": "ok"}


@router.post(
    "/project/update",
    response_model=UpdateProjectResponse,
    dependencies=[Depends(RateLimiter(rate=os.environ["FORMATTED_RATE_PROJECT"], identifier_type="uid"))]
)
async def update_project(
        request: UpdateProjectRequest,
        conn: AsyncConnection = Depends(get_connection),
        user_id: Optional[str] = Header(None, alias="x-user-id")
):
    """
    Update project information.
    """
    if not user_id:
        raise HTTPException(status_code=400, detail="Missing user ID")
    querier = AsyncQuerier(conn)
    project = await querier.update_project(UpdateProjectParams(
        owner_id=int(user_id),
        name=request.name,
        description=request.description,
        configuration=request.configuration,
        updated_at=datetime.datetime.now(datetime.timezone.utc)
    ))
    if not project:
        raise HTTPException(status_code=404, detail="Project update failed")
    return UpdateProjectResponse(name=project.name)


@router.post(
    "/project/list",
    response_model=ListProjectResponse,
    dependencies=[Depends(RateLimiter(rate=os.environ["FORMATTED_RATE_PROJECT"], identifier_type="uid"))]
)
async def list_project(
        request: ListProjectsRequest,
        conn: AsyncConnection = Depends(get_connection),
        user_id: Optional[str] = Header(None, alias="x-user-id")
):
    """
    List projects.
    """
    if not user_id:
        raise HTTPException(status_code=400, detail="Missing user ID")
    querier = AsyncQuerier(conn)
    projects = [name async for name in querier.list_projects(
        owner_id=int(user_id),
        limit=request.limit,
        offset=request.offset
    )]
    return ListProjectResponse(projects=projects)


@router.post(
    "/project/create_release",
    response_model=CreateReleasedProjectResponse,
    dependencies=[Depends(RateLimiter(rate=os.environ["FORMATTED_RATE_PROJECT"], identifier_type="uid"))]
)
async def create_released_project(
        request: CreateReleasedProjectRequest,
        conn: AsyncConnection = Depends(get_connection),
        user_id: Optional[str] = Header(None, alias="x-user-id")
):
    """
    Create a released project.
    """
    if not user_id:
        raise HTTPException(status_code=400, detail="Missing user ID")
    querier = AsyncQuerier(conn)
    project = await querier.get_project_by_name(
        owner_id=int(user_id),
        name=request.name
    )
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    querier = ReleasedAsyncQuerier(conn)
    try:
        release = await querier.create_released_project(CreateReleasedProjectParams(
            owner_id=int(user_id),
            name=request.name,
            tag=request.tag,
            description=project.description,
            configuration=project.configuration
        ))
        return CreateReleasedProjectResponse(name=release.name, tag=release.tag)
    except sqlalchemy.exc.IntegrityError as e:
        if isinstance(e.orig, psycopg.errors.UniqueViolation):
            raise HTTPException(status_code=409, detail="Project release already exists") from e


@router.get(
    "/project/get_release",
    response_model=GetReleasedProjectResponse,
    dependencies=[Depends(RateLimiter(rate=os.environ["FORMATTED_RATE_PROJECT"], identifier_type="uid"))]
)
async def get_released_project(
        name: str,
        tag: str,
        conn: AsyncConnection = Depends(get_connection),
        user_id: Optional[str] = Header(None, alias="x-user-id")
):
    """
    Query released project information.
    """
    if not user_id:
        raise HTTPException(status_code=400, detail="Missing user ID")
    querier = ReleasedAsyncQuerier(conn)
    project = await querier.get_released_project_by_name_and_tag(
        owner_id=int(user_id),
        name=name,
        tag=tag
    )
    if not project:
        raise HTTPException(status_code=404, detail="Project release not found")
    return GetReleasedProjectResponse(
        name=project.name,
        tag=project.tag,
        description=project.description,
        configuration=project.configuration,
        created_at=project.created_at,
    )


@router.post(
    "/project/list_release",
    response_model=ListProjectResponse,
    dependencies=[Depends(RateLimiter(rate=os.environ["FORMATTED_RATE_PROJECT"], identifier_type="uid"))]
)
async def list_released_project(
        request: ListProjectsRequest,
        conn: AsyncConnection = Depends(get_connection),
        user_id: Optional[str] = Header(None, alias="x-user-id")
):
    """
    List released projects.
    """
    if not user_id:
        raise HTTPException(status_code=400, detail="Missing user ID")
    querier = ReleasedAsyncQuerier(conn)
    projects = [name async for name in querier.list_released_projects(
        owner_id=int(user_id),
        limit=request.limit,
        offset=request.offset
    )]
    return ListProjectResponse(projects=projects)
