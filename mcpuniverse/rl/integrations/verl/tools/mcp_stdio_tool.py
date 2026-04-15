"""
MCP stdio tool wrapper for verl's ToolAgentLoop.

Spawns MCP servers via stdio transport and wraps each tool as a verl BaseTool.
"""
# pylint: disable=import-outside-toplevel

import asyncio
import json
import logging
import os
import threading
from contextlib import AsyncExitStack
from datetime import timedelta
from typing import Any, Optional

from mcp import StdioServerParameters, ClientSession
from mcp.client.stdio import stdio_client

from verl.tools.base_tool import BaseTool
from verl.tools.schemas import OpenAIFunctionToolSchema, ToolResponse

logger = logging.getLogger(__name__)


class MCPStdioTool(BaseTool):
    """A verl-compatible tool backed by an MCP stdio server.

    Each instance wraps a single tool from an MCP server. The server is
    started lazily on first ``execute`` call and shared across instances
    from the same server via a class-level connection pool.
    """

    # Class-level MCP client pool: {server_key: (session, exit_stack, lock)}
    _pool: dict[str, tuple[ClientSession, AsyncExitStack, asyncio.Lock]] = {}
    _pool_lock = threading.Lock()

    def __init__(self, config: dict, tool_schema: OpenAIFunctionToolSchema):
        super().__init__(config, tool_schema)
        self._server_command = config["command"]
        self._server_args = config["args"]
        self._timeout = config.get("timeout", 30)
        self._server_key = f"{self._server_command}:{' '.join(self._server_args)}"

    @classmethod
    async def _get_session(cls, server_key: str, command: str, args: list[str],
                           timeout: int) -> ClientSession:
        """Get or create an MCP client session for the given server."""
        if server_key in cls._pool:
            return cls._pool[server_key][0]

        stack = AsyncExitStack()
        params = StdioServerParameters(
            command=command,
            args=args,
            env=dict(os.environ),
        )
        transport = await stack.enter_async_context(stdio_client(params))
        read, write = transport
        session = await stack.enter_async_context(
            ClientSession(read, write, read_timeout_seconds=timedelta(seconds=timeout))
        )
        await session.initialize()
        lock = asyncio.Lock()
        cls._pool[server_key] = (session, stack, lock)
        logger.info("MCPStdioTool: started server %s", server_key)
        return session

    async def execute(self, instance_id: str, parameters: dict[str, Any],
                      **kwargs) -> tuple[ToolResponse, float, dict]:
        """Execute the tool via MCP call_tool."""
        try:
            session = await self._get_session(
                self._server_key, self._server_command, self._server_args, self._timeout
            )
            result = await session.call_tool(self.name, arguments=parameters)
            text_parts = [
                part.text for part in result.content
                if hasattr(part, 'text')
            ]
            result_text = " ".join(text_parts)
            return ToolResponse(text=result_text), 0.0, {}
        except Exception as e:
            error_msg = f"MCP tool {self.name} failed: {e}"
            logger.error(error_msg)
            return ToolResponse(text=json.dumps({"error": error_msg})), 0.0, {"error": str(e)}

    @classmethod
    async def cleanup_all(cls):
        """Shut down all MCP server connections."""
        for key, (_, stack, _) in list(cls._pool.items()):
            try:
                await stack.aclose()
            except Exception:
                pass
        cls._pool.clear()


def create_mcp_stdio_tools(server_name: str, command: str, args: list[str],
                           timeout: int = 30,
                           tool_filter: Optional[list[str]] = None) -> list[MCPStdioTool]:
    """Discover tools from an MCP stdio server and return verl-compatible tool instances.

    Args:
        server_name: Human-readable server name (for logging).
        command: Command to start the MCP server (e.g. "python3").
        args: Arguments for the command (e.g. ["-m", "mcpuniverse.mcp.servers.yahoo_finance"]).
        timeout: MCP session timeout in seconds.
        tool_filter: Optional list of tool names to include. If None, all tools are included.

    Returns:
        List of MCPStdioTool instances, one per tool.
    """
    async def _discover():
        params = StdioServerParameters(command=command, args=args, env=dict(os.environ))
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write,
                                     read_timeout_seconds=timedelta(seconds=timeout)) as session:
                await session.initialize()
                tools_result = await session.list_tools()
                return tools_result.tools

    # Run discovery synchronously
    mcp_tools = asyncio.run(_discover())

    verl_tools = []
    for t in mcp_tools:
        if tool_filter and t.name not in tool_filter:
            continue

        # Build OpenAI function schema
        schema = OpenAIFunctionToolSchema.model_validate({
            "type": "function",
            "function": {
                "name": t.name,
                "description": t.description or "",
                "parameters": t.inputSchema or {"type": "object", "properties": {}},
            }
        })

        config = {
            "type": "native",  # verl expects this
            "command": command,
            "args": args,
            "timeout": timeout,
        }

        tool = MCPStdioTool(config=config, tool_schema=schema)
        verl_tools.append(tool)
        logger.info("MCPStdioTool: registered %s.%s", server_name, t.name)

    return verl_tools
