"""
MCP proxy server that wraps another MCP server and post-processes tool outputs.

This server exposes the same tools as the upstream MCP server, but routes calls
through MCP+'s WrappedMCPClient so long outputs can be filtered by the
post-processing agent before being returned to the caller.
"""
# pylint: disable=protected-access,broad-exception-caught,no-value-for-parameter,line-too-long
import asyncio
import json
import keyword
import os
import shlex
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Any

import click
from mcp.server.fastmcp import FastMCP, Context as FastMCPContext
from mcp.types import ToolAnnotations

from mcpuniverse.common.logger import get_logger
from mcpuniverse.extensions.mcpplus.wrapper.wrapper_manager import MCPWrapperManager, WrapperConfig  # pylint: disable=no-name-in-module
from mcpuniverse.llm.manager import ModelManager
from mcpuniverse.common.context import Context


@dataclass
class ProxyConfig:
    """Configuration for the proxy server."""

    upstream_server: str
    server_name: str = "proxy"
    transport: str = "stdio"  # transport to talk to upstream (stdio, sse, or http)
    upstream_address: str = ""  # used for sse/http
    timeout: int = 30
    wrapper: Optional[dict] = None  # WrapperConfig fields
    llm: Optional[dict] = None  # Optional LLM config for post-processing
    headers: Optional[dict] = None  # HTTP headers for authentication (used for http/sse)
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
        headers=data.get("headers"),
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
            instructions=f"MCP+ enabled version of '{self._config.upstream_server}' with intelligent output post-processing to reduce token costs.",
        )

    async def _init_client(self):  # pylint: disable=too-many-statements
        """Build a wrapped client to the upstream server."""
        # Initialize manager with wrapper support
        wrapper_cfg = WrapperConfig(**(self._config.wrapper or {})) if self._config.wrapper else None
        self._mcp_manager = MCPWrapperManager(wrapper_config=wrapper_cfg)

        # Load server configs from bundled server_list.json
        config_file = Path(__file__).parent / "configs" / "server_list.json"
        if config_file.exists():
            self._mcp_manager.load_configs(str(config_file))

        # Register the server dynamically (stdio, SSE, or HTTP)
        # This allows wrapping servers not in server_list.json
        if self._config.transport == "http" and self._config.upstream_address:
            # HTTP server with direct URL
            server_config = {
                "http_url": self._config.upstream_address,
            }
            # Add headers if provided
            if self._config.headers:
                server_config["headers"] = self._config.headers
            try:
                self._mcp_manager.add_server_config(self._config.upstream_server, server_config)
            except ValueError:
                # Server already exists, update it instead
                self._mcp_manager.update_server_config(self._config.upstream_server, server_config)
            self._logger.info(
                "Registered HTTP server '%s' with URL: %s",
                self._config.upstream_server,
                self._config.upstream_address
            )
        elif self._config.transport == "sse" and self._config.upstream_address:
            # SSE server with direct URL
            # Register a minimal config so the server is known to the manager
            server_config = {
                "sse": {
                    "command": self._config.upstream_address,  # Store URL in command field
                    "args": [],
                }
            }
            # Add headers if provided (for authenticated SSE)
            if self._config.headers:
                server_config["headers"] = self._config.headers
            try:
                self._mcp_manager.add_server_config(self._config.upstream_server, server_config)
            except ValueError:
                # Server already exists, update it instead
                self._mcp_manager.update_server_config(self._config.upstream_server, server_config)
            self._logger.info(
                "Registered SSE server '%s' with URL: %s",
                self._config.upstream_server,
                self._config.upstream_address
            )
        elif self._config.upstream_command is not None and self._config.upstream_args is not None:
            # stdio server
            # Split command string if it contains arguments
            # (Cursor config sometimes has "npx -y @playwright/mcp" as single string)
            if isinstance(self._config.upstream_command, str) and ' ' in self._config.upstream_command:
                # Command contains spaces - need to split it
                if self._config.upstream_args:
                    # Args already provided separately, just split the command
                    cmd_parts = shlex.split(self._config.upstream_command)
                    command = cmd_parts[0]
                    args = cmd_parts[1:] + self._config.upstream_args
                else:
                    # No separate args, split entire command string
                    cmd_parts = shlex.split(self._config.upstream_command)
                    command = cmd_parts[0]
                    args = cmd_parts[1:]
            else:
                # Command is just the executable
                command = self._config.upstream_command
                args = self._config.upstream_args

            server_config = {
                "stdio": {
                    "command": command,
                    "args": args,
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
                command,
                " ".join(args)
            )

        # Resolve post-processing LLM if provided
        if self._config.llm:
            llm_manager = ModelManager()
            # Expand env vars in config (e.g., "$OPENAI_API_KEY" -> actual value)
            llm_config = self._config.llm.copy()
            if "config" in llm_config and isinstance(llm_config["config"], dict):
                llm_config["config"] = llm_config["config"].copy()

                # Expand api_key
                api_key = llm_config["config"].get("api_key", "")
                if isinstance(api_key, str) and api_key.startswith("$"):
                    env_var = api_key[1:]  # Remove leading $
                    expanded_key = os.environ.get(env_var, "")
                    llm_config["config"]["api_key"] = expanded_key
                    self._logger.debug("Expanded $%s for api_key (length: %d)", env_var, len(expanded_key))

                # Expand env-backed config fields (gateway / Azure providers)
                for field in ("base_url", "azure_endpoint", "api_version"):
                    value = llm_config["config"].get(field, "")
                    if isinstance(value, str) and value.startswith("$"):
                        env_var = value[1:]
                        expanded = os.environ.get(env_var, "")
                        llm_config["config"][field] = expanded
                        self._logger.debug("Expanded $%s for %s: %s", env_var, field, expanded)

                self._logger.debug("Final LLM config - provider: %s, base_url: %s",
                                   llm_config['name'], llm_config['config'].get('base_url', 'NOT SET'))
            llm = llm_manager.build_model(**llm_config)
            llm.set_context(Context(env=dict(os.environ)))
            self._mcp_manager.set_llm(llm)
        else:
            self._logger.warning(
                "No LLM config provided; wrapper must rely on agent-provided LLM via set_llm() "
                "or post-processing will be disabled when use_agent_llm=True."
            )

        # Try to build client with specified transport, with fallback if needed
        transport_tried = self._config.transport
        try:
            self._client = await self._mcp_manager.build_client(
                server_name=self._config.upstream_server,
                transport=transport_tried,
                timeout=self._config.timeout,
                mcp_gateway_address=self._config.upstream_address,
                headers=self._config.headers,
            )
            self._logger.info(
                "Successfully connected to upstream '%s' via %s transport",
                self._config.upstream_server,
                transport_tried
            )
        except Exception as e:
            # If HTTP fails and we have a URL, try SSE fallback
            if transport_tried == "http" and self._config.upstream_address:
                self._logger.warning(
                    "Failed to connect via HTTP transport: %s. Trying SSE fallback...",
                    str(e)
                )
                try:
                    # Try SSE as fallback
                    # Re-register the server with SSE config instead of HTTP
                    sse_config = {
                        "sse": {
                            "command": self._config.upstream_address,
                            "args": [],
                        }
                    }
                    if self._config.headers:
                        sse_config["headers"] = self._config.headers

                    try:
                        self._mcp_manager.update_server_config(self._config.upstream_server, sse_config)
                    except Exception:
                        # If update fails, try adding fresh
                        self._mcp_manager.add_server_config(self._config.upstream_server, sse_config)

                    self._client = await self._mcp_manager.build_client(
                        server_name=self._config.upstream_server,
                        transport="sse",
                        timeout=self._config.timeout,
                        mcp_gateway_address=self._config.upstream_address,
                        headers=self._config.headers,
                    )
                    self._logger.info(
                        "Successfully connected to upstream '%s' via SSE fallback",
                        self._config.upstream_server
                    )
                except Exception as sse_error:
                    self._logger.error(
                        "Failed to connect to upstream '%s' via both HTTP and SSE: HTTP error: %s, SSE error: %s",
                        self._config.upstream_server,
                        str(e),
                        str(sse_error)
                    )
                    raise RuntimeError(
                        f"Could not connect to upstream server '{self._config.upstream_server}' "
                        f"via HTTP or SSE transport"
                    ) from sse_error
            else:
                self._logger.error(
                    "Failed to connect to upstream '%s' via %s transport: %s",
                    self._config.upstream_server,
                    transport_tried,
                    str(e)
                )
                raise

    async def start(self):  # pylint: disable=too-many-statements,too-many-locals,too-many-branches
        """Start the proxy server by binding handlers and initializing the upstream client."""
        try:
            await self._init_client()
        except Exception as e:
            self._logger.error("Failed to initialize upstream client: %s", str(e))
            self._logger.error(
                "Proxy server '%s' will start but will not have any tools available.",
                self._config.server_name
            )
            # Don't raise - allow proxy to start (it just won't have tools)
            return

        # Mirror upstream tools as first-class FastMCP tools
        try:
            tools = await self._client.list_tools()
        except Exception as e:
            self._logger.error("Failed to list tools from upstream: %s", str(e))
            self._logger.error(
                "Proxy server '%s' will start but will not have any tools available.",
                self._config.server_name
            )
            return
        # Pull expected_info description from wrapped client if available
        expected_info_desc = None
        if hasattr(self._client, "_get_expected_info_description"):
            expected_info_desc = self._client._get_expected_info_description()

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

            required_params = []
            optional_params = []
            used_param_names: set = set()

            def _make_safe_name(name: str, used_names: set) -> str:
                safe_name = name
                if not safe_name.isidentifier() or keyword.iskeyword(safe_name):
                    safe_name = "".join(ch if ch.isalnum() or ch == "_" else "_" for ch in safe_name)
                    if not safe_name or safe_name[0].isdigit():
                        safe_name = f"param_{safe_name}"
                    if keyword.iskeyword(safe_name):
                        safe_name = f"{safe_name}_param"
                base_name = safe_name
                suffix = 1
                while safe_name in used_names:
                    safe_name = f"{base_name}_{suffix}"
                    suffix += 1
                used_names.add(safe_name)
                return safe_name

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

                safe_name = _make_safe_name(pname, used_param_names)
                if pname in required:
                    required_params.append((safe_name, pname, ann))
                else:
                    optional_params.append((safe_name, pname, ann))

            # Ensure expected_info exists (wrapper added it upstream)
            actual_names = {pname for _, pname, _ in required_params + optional_params}
            if "expected_info" not in actual_names:
                safe_name = _make_safe_name("expected_info", used_param_names)
                required_params.append((safe_name, "expected_info", "str"))
                required.add("expected_info")

            param_parts = [f"{pname}: {ann}" for pname, _, ann in required_params]
            param_parts += [
                f"{pname}: {ann} | None = None" for pname, _, ann in optional_params
            ]
            param_names = [(pname, actual) for pname, actual, _ in required_params + optional_params]

            signature = ", ".join(param_parts)
            # Add ctx parameter for progress reporting
            lines = [f"async def _tool(ctx: FastMCPContext, {signature}):"]
            lines.append("    args = {}")
            for pname, actual_name in param_names:
                # always include required fields; include optional if not None
                lines.append(
                    f"    if {actual_name!r} in {list(required)!r} or {pname} is not None:"
                )
                lines.append(f"        args[{actual_name!r}] = {pname}")
            # Safety: if expected_info still missing, provide a default to trigger wrapper
            lines.append("    if 'expected_info' not in args:")
            lines.append("        args['expected_info'] = 'All information is needed; summarize concisely.'")
            lines.append(f"    return await client.execute_tool(tool_name='{tool_name}', arguments=args)")

            fn_src = "\n".join(lines)
            local_vars: dict[str, Any] = {}
            exec(fn_src, {"client": self._client, "FastMCPContext": FastMCPContext}, local_vars)  # pylint: disable=exec-used
            tool_fn = local_vars["_tool"]

            # Modify input schema to include expected_info parameter
            modified_schema = dict(input_schema) if isinstance(input_schema, dict) else {}
            if "properties" not in modified_schema:
                modified_schema["properties"] = {}
            if "required" not in modified_schema:
                modified_schema["required"] = []
            # Add expected_info to schema (using same description as PJ's WrappedMCPClient)
            modified_schema["properties"]["expected_info"] = {
                "type": "string",
                "description": (
                    'A precise description of what specific information you need from this tool call to accomplish your immediate goal. '
                    'Be explicit about:\n'
                    '1. WHAT data/information you need (e.g., "the adult ticket price", "list of product URLs", "error message text")\n'
                    '2. WHY you need it (e.g., "to answer the user\'s question", "to visit in the next step", "to debug the issue")\n'
                    '3. Any CONSTRAINTS (e.g., "only from the pricing section", "maximum 10 items", "published after 2023")\n'
                    'Example good descriptions:\n'
                    '  - "The adult ticket price for ABC Theatre from the pricing table, needed to answer the user\'s question about ticket cost"\n'
                    '  - "URLs of all product links on the page, needed to visit each product page in subsequent steps"\n'
                    'Example bad descriptions:\n'
                    '  - "get information" (too vague)\n'
                    '  - "price" (unclear which price, why needed, from where)\n'
                    '  - "check the page" (not specific about what to extract)'
                ),
            }
            if "expected_info" not in modified_schema["required"]:
                modified_schema["required"].append("expected_info")

            self._server.add_tool(
                fn=tool_fn,
                name=tool_name,
                description=tool_desc,
                annotations=ToolAnnotations(input_schema=modified_schema),
            )

        # Mirror upstream prompts (no post-processing needed - they're just templates)
        try:
            prompts = await self._client.list_prompts()
            for prompt in prompts:
                prompt_name = getattr(prompt, "name", None)
                prompt_desc = getattr(prompt, "description", None)
                if not prompt_name:
                    continue

                # Create a closure to capture the prompt_name correctly
                def make_prompt_handler(pname: str):
                    async def prompt_handler(arguments: dict = None):
                        """Forward prompt request to upstream server."""
                        return await self._client.get_prompt(pname, arguments or {})
                    return prompt_handler

                # Use the prompt decorator programmatically
                handler = make_prompt_handler(prompt_name)
                self._server.prompt(
                    name=prompt_name,
                    description=prompt_desc or f"Prompt from upstream: {prompt_name}"
                )(handler)
            self._logger.info("Mirrored %d prompts from upstream server", len(prompts))
        except Exception as e:
            self._logger.warning("Failed to mirror prompts from upstream: %s", str(e))

        # Mirror upstream resources with URI rewriting
        # Rewrite non-RFC-compliant URIs (e.g., "browser/screenshot") to valid URIs ("internal://browser/screenshot")
        try:
            from mcp import types as mcp_types  # pylint: disable=import-outside-toplevel

            # Get resources from upstream - make raw request to bypass validation
            resources_list = []
            try:
                # Make raw JSON-RPC request to get resources without validation
                if hasattr(self._client, '_session') and self._client._session:
                    # pylint: disable=import-outside-toplevel
                    from mcp.shared.session import JSONRPCRequest, SessionMessage, JSONRPCMessage
                    import anyio

                    request_id = getattr(self._client._session, '_request_id', 1)
                    jsonrpc_request = JSONRPCRequest(
                        jsonrpc="2.0",
                        id=request_id,
                        method="resources/list",
                        params=None
                    )

                    response_stream, response_stream_reader = anyio.create_memory_object_stream(1)
                    if hasattr(self._client._session, '_response_streams'):
                        self._client._session._response_streams[request_id] = response_stream
                        if hasattr(self._client._session, '_request_id'):
                            self._client._session._request_id = request_id + 1

                    await self._client._session._write_stream.send(
                        SessionMessage(message=JSONRPCMessage(jsonrpc_request), metadata=None)
                    )

                    try:
                        with anyio.fail_after(30.0):
                            response_or_error = await response_stream_reader.receive()
                    finally:
                        if hasattr(self._client._session, '_response_streams'):
                            self._client._session._response_streams.pop(request_id, None)
                        await response_stream.aclose()
                        await response_stream_reader.aclose()

                    # Parse raw response - check if it's an error first
                    if hasattr(response_or_error, 'error'):
                        # This is a JSONRPCError
                        self._logger.warning("Upstream returned error for resources/list: %s", response_or_error.error)
                        raw_result = None
                    else:
                        raw_result = response_or_error.result

                    if raw_result and isinstance(raw_result, dict) and 'resources' in raw_result:
                        for res_dict in raw_result['resources']:
                            uri = res_dict.get('uri', '')
                            # If URI doesn't have a scheme, add "mcpplus-proxy://" prefix
                            if '://' not in uri:
                                uri = f"mcpplus-proxy://{uri}"

                            resources_list.append({
                                "uri": uri,
                                "name": res_dict.get('name'),
                                "description": res_dict.get('description'),
                                "mimeType": res_dict.get('mimeType'),
                            })
                        self._logger.info("Retrieved %d resources from upstream (rewrote %d URIs)",
                                         len(resources_list),
                                         sum(1 for r in resources_list if r['uri'].startswith('mcpplus-proxy://')))
                else:
                    self._logger.warning("Client session not available for raw resource listing")
            except Exception as list_error:
                self._logger.warning("Failed to list resources from client: %s", str(list_error))

            # Define handlers with URI rewriting
            async def list_resources_handler(_request):
                """Return resources with rewritten URIs."""
                result_resources = [mcp_types.Resource(**res_dict) for res_dict in resources_list]
                result = mcp_types.ListResourcesResult(resources=result_resources)
                return mcp_types.ServerResult(result)

            async def read_resource_handler(request):  # pylint: disable=too-many-return-statements
                """Forward resource read to upstream using raw JSON-RPC (bypasses URI validation)."""
                uri = str(request.params.uri)

                # Strip "mcpplus-proxy://" prefix before forwarding to upstream
                if uri.startswith('mcpplus-proxy://'):
                    stripped = uri[len('mcpplus-proxy://'):]

                    # Validation: check for nested schemes (suspicious)
                    if '://' in stripped:
                        error_msg = f"Suspicious nested URI scheme detected: {uri}"
                        self._logger.error(error_msg)
                        return mcp_types.ServerResult(
                            mcp_types.ReadResourceResult(contents=[
                                mcp_types.TextResourceContents(
                                    uri=uri,
                                    mimeType="text/plain",
                                    text=f"Error: {error_msg}"
                                )
                            ])
                        )

                    uri = stripped
                    self._logger.debug("Reading resource with rewritten URI: %s", uri)

                # Basic validation
                if not uri or not isinstance(uri, str):
                    error_msg = "Invalid URI: must be a non-empty string"
                    self._logger.error(error_msg)
                    return mcp_types.ServerResult(
                        mcp_types.ReadResourceResult(contents=[
                            mcp_types.TextResourceContents(
                                uri=uri,
                                mimeType="text/plain",
                                text=f"Error: {error_msg}"
                            )
                        ])
                    )

                # Make raw JSON-RPC request to bypass client-side validation
                try:
                    if hasattr(self._client, '_session') and self._client._session:
                        # pylint: disable=import-outside-toplevel
                        from mcp.shared.session import JSONRPCRequest, SessionMessage, JSONRPCMessage
                        import anyio

                        request_id = getattr(self._client._session, '_request_id', 1)
                        jsonrpc_request = JSONRPCRequest(
                            jsonrpc="2.0",
                            id=request_id,
                            method="resources/read",
                            params={"uri": uri}
                        )

                        response_stream, response_stream_reader = anyio.create_memory_object_stream(1)
                        if hasattr(self._client._session, '_response_streams'):
                            self._client._session._response_streams[request_id] = response_stream
                            if hasattr(self._client._session, '_request_id'):
                                self._client._session._request_id = request_id + 1

                        await self._client._session._write_stream.send(
                            SessionMessage(message=JSONRPCMessage(jsonrpc_request), metadata=None)
                        )

                        try:
                            with anyio.fail_after(30.0):
                                response_or_error = await response_stream_reader.receive()
                        finally:
                            if hasattr(self._client._session, '_response_streams'):
                                self._client._session._response_streams.pop(request_id, None)
                            await response_stream.aclose()
                            await response_stream_reader.aclose()

                        # Check for error response
                        from mcp.shared.session import JSONRPCError  # pylint: disable=import-outside-toplevel
                        if isinstance(response_or_error, JSONRPCError):
                            error_msg = f"Upstream error: {response_or_error.error}"
                            self._logger.error(error_msg)
                            return mcp_types.ServerResult(
                                mcp_types.ReadResourceResult(contents=[
                                    mcp_types.TextResourceContents(
                                        uri=uri,
                                        mimeType="text/plain",
                                        text=error_msg
                                    )
                                ])
                            )

                        # Parse response and rewrite URIs
                        raw_result = response_or_error.result
                        if isinstance(raw_result, dict) and 'contents' in raw_result:
                            # Rewrite URIs in response contents to add mcpplus-proxy:// prefix
                            for content in raw_result.get('contents', []):
                                if isinstance(content, dict) and 'uri' in content:
                                    content_uri = content['uri']
                                    # Add prefix if URI doesn't have a scheme
                                    if isinstance(content_uri, str) and '://' not in content_uri:
                                        content['uri'] = f"mcpplus-proxy://{content_uri}"
                                        self._logger.debug("Rewrote response URI: %s → %s", content_uri, content['uri'])

                            # Now parse with rewritten URIs (valid schemes)
                            result = mcp_types.ReadResourceResult(**raw_result)
                            return mcp_types.ServerResult(result)

                        # Unexpected format
                        return mcp_types.ServerResult(raw_result)

                    error_msg = "Client session not available"
                    self._logger.error(error_msg)
                    return mcp_types.ServerResult(
                        mcp_types.ReadResourceResult(contents=[
                            mcp_types.TextResourceContents(
                                uri=uri,
                                mimeType="text/plain",
                                text=f"Error: {error_msg}"
                            )
                        ])
                    )
                except Exception as e:
                    error_msg = f"Failed to read resource: {str(e)}"
                    self._logger.error(error_msg)
                    import traceback  # pylint: disable=import-outside-toplevel
                    self._logger.debug("Traceback: %s", traceback.format_exc())
                    return mcp_types.ServerResult(
                        mcp_types.ReadResourceResult(contents=[
                            mcp_types.TextResourceContents(
                                uri=uri,
                                mimeType="text/plain",
                                text=error_msg
                            )
                        ])
                    )

            # Override FastMCP's resource handlers
            underlying_server = self._server._mcp_server
            underlying_server.request_handlers[mcp_types.ListResourcesRequest] = list_resources_handler
            underlying_server.request_handlers[mcp_types.ReadResourceRequest] = read_resource_handler

            self._logger.info("Registered %d resources with URI rewriting", len(resources_list))
        except Exception as e:
            self._logger.warning("Failed to setup resource handlers: %s", str(e))

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
