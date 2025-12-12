"""
MCP proxy server that wraps another MCP server and post-processes tool outputs.

This server exposes the same tools as the upstream MCP server, but routes calls
through MCP+'s WrappedMCPClient so long outputs can be filtered by the
post-processing agent before being returned to the caller.
"""
# pylint: disable=protected-access,broad-exception-caught
import asyncio
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Any

import click
from mcp.server.fastmcp import FastMCP, Context as FastMCPContext
from mcp.types import CallToolResult, TextContent, ToolAnnotations

from mcpuniverse.mcpplus.common.logger import get_logger
from mcpuniverse.mcpplus.mcp.wrapper_manager import MCPWrapperManager, WrapperConfig
from mcpuniverse.mcp.manager import MCPManager
from mcpuniverse.llm.manager import ModelManager
from mcpuniverse.common.context import Context


@dataclass
class ProxyConfig:
    """Configuration for the proxy server."""

    upstream_server: str
    server_name: str = "proxy"
    transport: str = "stdio"  # transport to talk to upstream (stdio or sse)
    upstream_address: str = ""  # used for sse
    timeout: int = 30
    wrapper: Optional[dict] = None  # WrapperConfig fields
    llm: Optional[dict] = None  # Optional LLM config for post-processing
    # Direct upstream launch config (used when server not in server_list.json)
    upstream_command: Optional[str] = None
    upstream_args: Optional[list] = None
    upstream_env: Optional[dict] = None


def _load_config(path: str) -> ProxyConfig:
    """Load proxy config from JSON file."""
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)

    wrapper_dict = data.get("wrapper", {}) or {}
    proxy_cfg = ProxyConfig(
        upstream_server=data["upstream_server"],
        server_name=data.get("server_name", "proxy"),
        transport=data.get("transport", "stdio"),
        upstream_address=data.get("upstream_address", ""),
        timeout=data.get("timeout", 30),
        wrapper=wrapper_dict,
        llm=data.get("llm"),
        upstream_command=data.get("upstream_command"),
        upstream_args=data.get("upstream_args"),
        upstream_env=data.get("upstream_env"),
    )
    return proxy_cfg


class ProxyServer:
    """Proxy MCP server that forwards to an upstream MCP server with wrapping."""

    def __init__(self, config: ProxyConfig):
        self._config = config
        self._logger = get_logger(self.__class__.__name__)
        self._mcp_manager: Optional[MCPWrapperManager] = None
        self._client = None
        self._server = FastMCP(
            self._config.server_name,
            instructions="Proxy MCP server with post-processing",
        )

    async def _init_client(self):
        """Build a wrapped client to the upstream server."""
        # Initialize manager with wrapper support
        wrapper_cfg = WrapperConfig(**(self._config.wrapper or {})) if self._config.wrapper else None
        self._mcp_manager = MCPWrapperManager(wrapper_config=wrapper_cfg)

        # Load server configs from bundled server_list.json
        config_file = Path(__file__).parent / "configs" / "server_list.json"
        self._mcp_manager.load_configs(str(config_file))

        # If upstream_command/args provided, register the server dynamically
        # This allows wrapping servers not in server_list.json
        if self._config.upstream_command and self._config.upstream_args is not None:
            server_config = {
                "stdio": {
                    "command": self._config.upstream_command,
                    "args": self._config.upstream_args,
                }
            }
            # Add env if provided
            if self._config.upstream_env:
                server_config["env"] = self._config.upstream_env
            try:
                self._mcp_manager.add_server_config(self._config.upstream_server, server_config)
            except ValueError:
                # Server already exists, update it instead
                self._mcp_manager.update_server_config(self._config.upstream_server, server_config)
            self._logger.info(
                "Registered upstream server '%s' with command: %s %s",
                self._config.upstream_server,
                self._config.upstream_command,
                " ".join(self._config.upstream_args)
            )

        # Resolve post-processing LLM if provided
        if self._config.llm:
            llm_manager = ModelManager()
            # Expand env vars in api_key (e.g., "$OPENAI_API_KEY" -> actual value)
            llm_config = self._config.llm.copy()
            if "config" in llm_config and isinstance(llm_config["config"], dict):
                llm_config["config"] = llm_config["config"].copy()
                api_key = llm_config["config"].get("api_key", "")
                if isinstance(api_key, str) and api_key.startswith("$"):
                    env_var = api_key[1:]  # Remove leading $
                    llm_config["config"]["api_key"] = os.environ.get(env_var, "")
            llm = llm_manager.build_model(**llm_config)
            llm.set_context(Context(env=dict(os.environ)))
            self._mcp_manager.set_llm(llm)
        else:
            self._logger.warning(
                "No LLM config provided; wrapper must rely on agent-provided LLM via set_llm() "
                "or post-processing will be disabled when use_agent_llm=True."
            )

        self._client = await self._mcp_manager.build_wrapped_client(
            server_name=self._config.upstream_server,
            transport=self._config.transport,
            timeout=self._config.timeout,
            mcp_gateway_address=self._config.upstream_address,
        )

    async def start(self):
        """Start the proxy server by binding handlers and initializing the upstream client."""
        await self._init_client()

        # Mirror upstream tools as first-class FastMCP tools
        tools = await self._client.list_tools()
        # Pull expected_info description from wrapped client if available
        expected_info_desc = None
        if hasattr(self._client, "_expected_info_description"):
            expected_info_desc = getattr(self._client, "_expected_info_description", None)

        for tool in tools:
            tool_name = getattr(tool, "name", None)
            tool_desc = getattr(tool, "description", None)
            if not tool_name:
                continue

            # Append expected_info guidance to the tool description for visibility
            if expected_info_desc:
                tool_desc = f"{tool_desc or ''}\n\nAdditional parameter: expected_info\n{expected_info_desc}"

            # Build a wrapper function with explicit signature to preserve schema
            input_schema = getattr(tool, "inputSchema", {}) or {}
            properties = input_schema.get("properties", {}) if isinstance(input_schema, dict) else {}
            required = set(input_schema.get("required", [])) if isinstance(input_schema, dict) else set()

            param_parts = []
            param_names = []
            for pname, schema in properties.items():
                stype = schema.get("type") if isinstance(schema, dict) else None
                ann = "str"
                if stype == "integer":
                    ann = "int"
                elif stype == "number":
                    ann = "float"
                elif stype == "boolean":
                    ann = "bool"
                elif stype == "array":
                    ann = "list"
                elif stype == "object":
                    ann = "dict"

                if pname in required:
                    param_parts.append(f"{pname}: {ann}")
                else:
                    param_parts.append(f"{pname}: {ann} | None = None")
                param_names.append(pname)

            # Ensure expected_info exists (wrapper added it upstream)
            if "expected_info" not in param_names:
                param_parts.append("expected_info: str")
                param_names.append("expected_info")
                required.add("expected_info")

            signature = ", ".join(param_parts)
            # Add ctx parameter for progress reporting
            lines = [f"async def _tool(ctx: FastMCPContext, {signature}):"]
            lines.append("    args = {}")
            for pname in param_names:
                # always include required fields; include optional if not None
                lines.append(f"    if '{pname}' in {list(required)!r} or {pname} is not None:")
                lines.append(f"        args['{pname}'] = {pname}")
            # Safety: if expected_info still missing, provide a default to trigger wrapper
            lines.append("    if 'expected_info' not in args:")
            lines.append("        args['expected_info'] = 'All information is needed; summarize concisely.'")
            # Create progress callback that wraps ctx.report_progress
            lines.append("    async def progress_callback(progress, total=None, message=None):")
            lines.append("        if hasattr(ctx, 'report_progress'):")
            lines.append("            await ctx.report_progress(progress, total, message)")
            lines.append(f"    return await client.execute_tool(tool_name='{tool_name}', arguments=args, progress_callback=progress_callback)")

            fn_src = "\n".join(lines)
            local_vars: dict[str, Any] = {}
            exec(fn_src, {"client": self._client, "FastMCPContext": FastMCPContext}, local_vars)  # pylint: disable=exec-used
            tool_fn = local_vars["_tool"]

            self._server.add_tool(
                fn=tool_fn,
                name=tool_name,
                description=tool_desc,
                annotations=ToolAnnotations(input_schema=getattr(tool, "inputSchema", None)),
            )

    async def run_async(self, transport: str = "stdio", port: int = 8000):
        """Run the FastMCP server with chosen transport (async)."""
        self._server.port = port
        transport = transport.lower()
        if transport == "stdio":
            await self._server.run_stdio_async()
        elif transport == "sse":
            await self._server.run_sse_async()
        elif transport == "streamable-http":
            await self._server.run_streamable_http_async()
        else:
            raise ValueError(f"Unknown transport: {transport}")

    def run(self, transport: str = "stdio", port: int = 8000):
        """Run the FastMCP server synchronously (wrapper around run_async)."""
        asyncio.run(self.run_async(transport=transport, port=port))


@click.command()
@click.option("--config", "config_path", required=True, help="Path to proxy config JSON")
@click.option("--transport", type=click.Choice(["stdio", "sse"]), default="stdio", help="Server transport to expose")
@click.option("--port", type=int, default=8000, help="Port for SSE transport")
def main(config_path: str, transport: str, port: int):
    """Entry point for running the proxy MCP server."""
    proxy_cfg = _load_config(config_path)
    server = ProxyServer(proxy_cfg)

    async def _run():
        await server.start()
        await server.run_async(transport=transport, port=port)

    asyncio.run(_run())


if __name__ == "__main__":
    main()  # pragma: no cover
