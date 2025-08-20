"""
API endpoints for chats.
"""
import os
from typing import Optional
from pydantic import BaseModel, Field
from fastapi import APIRouter, Depends, HTTPException, Header
from mcpuniverse.app.utils.limiter import RateLimiter
from mcpuniverse.app.core.engine import app_engine
from mcpuniverse.common.context import Context

router = APIRouter()


class ChatRequest(BaseModel):
    """Request schema for chatting."""
    project_name: str = Field(description="project name", min_length=1)
    config: str = Field(description="agent configuration in YAML format", max_length=50000)
    agent_name: str = Field(description="the name of the agent to answer the question")
    question: str = Field(description="question")
    context: Context = Field(default=None, description="context")


class ChatResponse(BaseModel):
    """Response schema for chatting."""
    response: str | dict = Field(description="agent response")


@router.post(
    "/chat",
    response_model=ChatResponse,
    dependencies=[Depends(RateLimiter(rate=os.environ["FORMATTED_RATE_CHAT"], identifier_type="uid"))]
)
async def chat(
        request: ChatRequest,
        user_id: Optional[str] = Header(None, alias="x-user-id")
):
    """
    Chat with a specified agent.
    """
    if not user_id:
        raise HTTPException(status_code=400, detail="Missing user ID")
    output = await app_engine.run(
        project_id=f"{user_id}-{request.project_name}",
        config=request.config,
        agent_name=request.agent_name,
        question=request.question,
        context=request.context
    )
    return ChatResponse(response=output)


@router.get(
    "/chat/get_component_response",
    response_model=ChatResponse,
    dependencies=[Depends(RateLimiter(rate=os.environ["FORMATTED_RATE_PUBLIC"], identifier_type="uid"))]
)
async def get_component_response(
        project_name: str,
        component_type: str,
        component_name: str,
        message_type: str = "response",
        user_id: Optional[str] = Header(None, alias="x-user-id")
):
    """
    Get agent component response.

    Args:
        project_name (str): The project name.
        component_type (str): The component type, i.e., llm, agent, workflow, mcp.
        component_name (str): The component name defined in the configuration.
        message_type (str | MessageType): The message type.
        user_id (str): The user ID.
    """
    if not user_id:
        raise HTTPException(status_code=400, detail="Missing user ID")
    if component_type not in ["llm", "agent", "workflow", "mcp"]:
        raise HTTPException(status_code=400, detail=f"Invalid component type `{component_type}`")
    output = app_engine.get_message(
        project_id=f"{user_id}-{project_name}",
        component_type=component_type,
        component_name=component_name,
        message_type=message_type
    )
    if output is None:
        return ChatResponse(response="")
    return ChatResponse(response=output.data)
