"""
Base classes for agents
"""
# pylint: disable=broad-exception-caught,unused-argument
import os
import uuid
import json
from abc import abstractmethod
from typing import List, Any, Dict, Union, Optional, Literal
from dataclasses import dataclass, field
from collections import OrderedDict
from pydantic import BaseModel

from mcpuniverse.common.config import BaseConfig
from mcpuniverse.common.misc import ComponentABCMeta, ExportConfigMixin
from mcpuniverse.mcp.manager import MCPManager, MCPClient
from mcpuniverse.llm.base import BaseLLM
from mcpuniverse.tracer import Tracer
from mcpuniverse.agent.types import AgentResponse
from mcpuniverse.callbacks.base import (
    BaseCallback,
    CallbackMessage,
    MessageType,
    Status,
    Event,
    send_message
)
from mcpuniverse.common.context import Context

DEFAULT_CONFIG_FOLDER = os.path.join(os.path.dirname(os.path.realpath(__file__)), "configs")
OUTPUT_FORMAT_PROMPT = """
The final answer should follow this JSON format:
{output_format}

You must respond with valid JSON only, with no triple backticks. No markdown formatting.
No extra text. Do not wrap in ```json code fences. Property names must be enclosed in double quotes.
""".strip()
TOOL_RESPONSE_SUMMARIZER_PROMPT = """
Extract all information from the tool response that is relevant to the context.

Tool Call Context:
{context}

Tool Response:
{tool_response}

Directly output the extracted information. Try to maintain the original response structure. Use fewer than 500 words.
""".strip()


@dataclass
class BaseAgentConfig(BaseConfig):
    """
    Configuration class for base agents.

    This class defines the common configuration parameters used by all agents.
    It includes settings for agent identification, instructions, prompt templates,
    server connections, and resources.

    Attributes:
        name (str): The name of the agent.
        instruction (str): A description or instruction for the agent's purpose.
        system_prompt (str): The system prompt template file or string.
        tools_prompt (str): The tools prompt template file or string.
        template_vars (dict): Additional variables for template rendering.
        servers (List[Dict]): List of server configurations. Each server dict can contain:
            - name (str): Server name (required)
            - transport (str): Transport type, "stdio" or "sse" (optional, default: "stdio")
            - tools (List[str]): List of specific tools to use from this server (optional)
            - permissions (List[Dict]): Permission rules for tool execution (optional)
                Each permission rule contains:
                - tool (str): Tool name or regex pattern (e.g., "*" for all tools)
                - arguments (Dict[str, str]): Argument constraints as key-value pairs (optional)
                - action (str): "allow", "reject", or "human_review" (default: "allow")
        resources (List[str]): List of resource identifiers.
        use_llm_tool_api (str): Whether to use LLM tool calling API, e.g., "yes" or "no".
        mcp_gateway_url (str, optional): MCP gateway server address.
    """
    # Agent name
    name: str = ""
    # Agent instruction/description
    instruction: str = ""
    # Prompt templates
    system_prompt: str = os.path.join(DEFAULT_CONFIG_FOLDER, "system_prompt.j2")
    tools_prompt: str = os.path.join(DEFAULT_CONFIG_FOLDER, "tools_prompt.j2")
    # Additional template variables
    template_vars: dict = field(default_factory=dict)
    # A list of servers with optional permissions:
    # Example: [{"name": "weather", "permissions": [{"tool": "*", "action": "human_review"}]}]
    servers: List[Dict[Literal["name", "transport", "tools", "permissions"], str | list]] = field(default_factory=list)
    # A list of resources
    resources: List[str] = field(default_factory=list)
    # Whether to use LLM tool calling API
    use_llm_tool_api: str = "no"
    # MCP gateway URL
    mcp_gateway_url: str = ""


class Executor:
    """
    The interface for agents and workflows.

    This abstract base class defines the common methods that all
    executors (agents and workflows) must implement.
    """

    @abstractmethod
    async def execute(self, message: Union[str, List[str]], **kwargs) -> AgentResponse:
        """Execute a command"""

    @abstractmethod
    async def initialize(self):
        """Initialize resources."""

    @abstractmethod
    async def cleanup(self):
        """Cleanup resources."""

    @abstractmethod
    def set_name(self, name: str):
        """Set a name."""

    def reset(self):
        """Reset the agent."""

    def get_children_ids(self) -> List[str]:
        """Return the IDs of child components."""
        return []


class BaseAgent(Executor, ExportConfigMixin, metaclass=ComponentABCMeta):
    """
    The base class for all agents.

    This class provides the fundamental structure and functionality
    for agents, including initialization, execution, and cleanup processes.
    It manages connections to MCP servers, handles tool execution, and
    provides methods for configuration management and tracing.

    Attributes:
        _config (BaseAgentConfig): The agent's configuration.
        _name (str): The agent's name.
        _mcp_manager (MCPManager): The MCP server manager.
        _llm (BaseLLM): The language model used by the agent.
        _mcp_clients (Dict[str, MCPClient]): A dictionary of MCP clients.
        _tools (Dict[str, Any]): A dictionary of available tools.
        _initialized (bool): Flag indicating if the agent is initialized.
    """

    def __init__(
            self,
            mcp_manager: MCPManager | None,
            llm: BaseLLM | None,
            config: Optional[Union[Dict, str]] = None,
    ):
        """
        Create a new agent.

        :param mcp_manager: An MCP server manager.
        :param llm: A LLM.
        :param config: Agent config (in dict or str).
        """
        self._config = self.config_class.load(config)
        # Agent name
        self._name: str = self._config.name if self._config.name else str(uuid.uuid4())
        self._config.name = self._name
        # Project ID
        self._project_id: str = ""
        # LLM setup
        self._llm: BaseLLM = llm
        # MCP setup
        self._mcp_manager: MCPManager = mcp_manager
        self._mcp_clients: Dict[str, MCPClient] = OrderedDict()
        self._tools: Dict[str, Any] = {}
        self._logger = None
        self._initialized: bool = False

    async def _initialize(self):
        """Initialize subclass."""

    async def initialize(self, mcp_servers: Optional[List[dict]] = None):
        """
        Initialize MCP clients and other resources.

        This method sets up the agent by creating MCP clients for each configured
        server and retrieving the available tools. It should be called before
        any execution takes place.

        Args:
            mcp_servers (List[dict], optional): A list of MCP servers.
                If not set, use the servers specified in the config.
                Each server dict supports:
                - name (str): Server name
                - transport (str): "stdio" or "sse" 
                - tools (List[str]): Specific tools to enable
                - permissions (List[Dict]): Tool permission rules
                    Format: [{"tool": "pattern", "action": "allow|reject|human_review", "arguments": {}}]
        """
        if self._initialized:
            return
        # Initialize MCP clients
        if mcp_servers is None:
            mcp_servers = self._config.servers
        self._mcp_clients = OrderedDict()
        for server in mcp_servers:
            server_name = server["name"]
            # Build client with optional permission configuration
            # Permissions format: [{"tool": "pattern", "action": "allow|reject|human_review", "arguments": {}}]
            client = await self._mcp_manager.build_client(
                server_name,
                transport=server.get("transport", "stdio"),
                permissions=server.get("permissions", None)
            )
            client.project_id = self._project_id
            self._mcp_clients[server_name] = client
        # Get the tools information
        self._tools = {}
        for server in mcp_servers:
            server_name = server["name"]
            tools = await self._mcp_clients[server_name].list_tools()
            selected_tools = server.get("tools", None)
            if selected_tools is None:
                self._tools[server_name] = tools
            else:
                self._tools[server_name] = [tool for tool in tools if tool.name in selected_tools]
        await self._initialize()
        self._initialized = True

    async def change_servers(self, mcp_servers: List[dict]):
        """
        Change MCP clients.

        This method sets up the agent by creating MCP clients for the specified
        server and retrieving the available tools.

        Args:
            mcp_servers (List[dict]): A list of MCP servers with optional permission configurations.
                Format: [{"name": "server", "permissions": [{"tool": "*", "action": "human_review"}]}]
        """
        await self.cleanup()
        await self.initialize(mcp_servers=mcp_servers)

    @abstractmethod
    async def _execute(self, message: Union[str, List[str]], **kwargs) -> AgentResponse:
        """Execute a command"""

    async def execute(self, message: Union[str, List[str]], **kwargs) -> AgentResponse:
        """
        Execute a command or process a message.

        This method handles the main execution flow of the agent, including
        tracing and error handling.

        Args:
            message (Union[str, List[str]]): The input message or command to process.
            **kwargs: Additional keyword arguments.

        Returns:
            AgentResponse: The response from the agent.

        Raises:
            AssertionError: If the agent is not initialized.
            Exception: Any exception that occurs during execution.
        """
        assert self._initialized, "The agent is not initialized."
        with kwargs.get("tracer", Tracer()).sprout() as tracer:
            if "tracer" in kwargs:
                kwargs.pop("tracer")
            trace_data = self.dump_config()
            callbacks = kwargs.get("callbacks", [])
            if "callbacks" in kwargs:
                kwargs.pop("callbacks")

            send_message(callbacks, message=CallbackMessage(
                source=self.id, type=MessageType.EVENT, data=Event.BEFORE_CALL,
                metadata={"method": "execute"}, project_id=self._project_id))
            send_message(callbacks, message=CallbackMessage(
                source=self.id, type=MessageType.STATUS, data=Status.RUNNING,
                project_id=self._project_id))
            try:
                response = await self._execute(message, tracer=tracer, callbacks=callbacks, **kwargs)
                trace_data.update({
                    "messages": [message] if not isinstance(message, str) else message,
                    "response": response.get_response(),
                    "response_type": response.get_response_type(),
                    "error": ""
                })
                tracer.add(trace_data)
            except Exception as e:
                trace_data.update({
                    "messages": [message] if not isinstance(message, str) else message,
                    "response": "",
                    "response_type": "str",
                    "error": str(e)
                })
                tracer.add(trace_data)
                send_message(callbacks, message=CallbackMessage(
                    source=self.id, type=MessageType.ERROR, data=str(e),
                    project_id=self._project_id))
                send_message(callbacks, message=CallbackMessage(
                    source=self.id, type=MessageType.EVENT, data=Event.AFTER_CALL,
                    metadata={"method": "execute"}, project_id=self._project_id))
                send_message(callbacks, message=CallbackMessage(
                    source=self.id, type=MessageType.STATUS, data=Status.FAILED,
                    project_id=self._project_id))
                raise e

            send_message(callbacks, message=CallbackMessage(
                source=self.id, type=MessageType.RESPONSE, data=response.get_response(),
                project_id=self._project_id))
            send_message(callbacks, message=CallbackMessage(
                source=self.id, type=MessageType.EVENT, data=Event.AFTER_CALL,
                metadata={"method": "execute"}, project_id=self._project_id))
            send_message(callbacks, message=CallbackMessage(
                source=self.id, type=MessageType.STATUS, data=Status.SUCCEEDED,
                project_id=self._project_id))
            return response

    @staticmethod
    def _get_output_format_prompt(output_format: Union[str, Dict]) -> str:
        """Return the output-format prompt."""
        if output_format is not None:
            if isinstance(output_format, dict):
                output_format_prompt = OUTPUT_FORMAT_PROMPT.format(
                    output_format=json.dumps(output_format, indent=2))
            else:
                output_format_prompt = output_format
            return output_format_prompt.strip()
        return ""

    async def _cleanup(self):
        """Cleanup subclass."""

    async def cleanup(self):
        """Cleanup resources."""
        if not self._initialized:
            return
        await self._cleanup()
        for _, client in list(self._mcp_clients.items())[::-1]:
            await client.cleanup()
        self._initialized = False

    def dump_config(self) -> Dict:
        """Dump the agent config"""
        return {
            "type": "agent",
            "class": self.__class__.__name__,
            "name": self._name,
            "config": self._config.to_dict() if self._config is not None else "",
            "llm_config": self._llm.dump_config() if self._llm is not None else ""
        }

    def get_description(self, with_tools_description=True) -> str:
        """Returns the agent description."""
        description = self._config.instruction if self._config.instruction else "No description"
        text = f"Agent name: {self._name}\nAgent description: {description}"
        if with_tools_description and len(self._tools) > 0:
            tool_names = []
            for server_name, tools in self._tools.items():
                tool_names.extend([f"{server_name}.{tool.name}" for tool in tools])
            text += f"\nAvailable tools: {', '.join(tool_names)}"
        return text

    def get_instruction(self) -> str:
        """Returns the agent instruction."""
        return self._config.instruction

    async def summarize_tool_response(self, tool_response: str, context: str, tracer: Tracer = None) -> str:
        """Summarize the tool response."""
        prompt = TOOL_RESPONSE_SUMMARIZER_PROMPT.format(
            context=context,
            tool_response=tool_response
        )
        tool_summary = await self._llm.generate_async(
            messages=[{"role": "user", "content": prompt}],
            tracer=tracer
        )
        return tool_summary

    async def call_tool(
            self,
            llm_response: Union[str, Dict],
            tracer: Tracer = None,
            callbacks: BaseCallback | List[BaseCallback] = None,
    ):
        """
        Call a specific tool indicated in a LLM response.

        This method parses the LLM response, identifies the tool to be called,
        and executes it using the appropriate MCP client. Tool execution is
        subject to permission rules configured for each server.

        Args:
            llm_response (Union[str, Dict]): The response from the language model,
                either as a JSON string or a dictionary.
                Expected format: {"server": "name", "tool": "tool_name", "arguments": {}}
            tracer (Tracer, optional): Tracer object for tracking model outputs.
                If None, a new Tracer will be created.
            callbacks (BaseCallback | List[BaseCallback], optional):
                Callbacks for recording MCP call status and responses

        Note:
            Tool execution may be blocked, allowed, or require human approval
            based on the permission rules configured for each server.

        Returns:
            Any: The result of the tool execution.

        Raises:
            RuntimeError: If the tool call fails for any reason (e.g., invalid format,
                          server not found, tool not found).
            json.JSONDecodeError: If the input string cannot be parsed as JSON.
        """
        tracer = tracer if tracer else Tracer()
        with tracer.sprout() as t:
            try:
                if isinstance(llm_response, str):
                    _response = llm_response.strip().strip('`').strip()
                    if _response.startswith("json"):
                        _response = _response[4:].strip()
                    tool_call = json.loads(_response)
                else:
                    tool_call = llm_response

                if "server" in tool_call and "tool" in tool_call and "arguments" in tool_call:
                    if tool_call["server"] not in self._tools:
                        raise RuntimeError(f"Not found server {tool_call['server']}")
                    for tool in self._tools[tool_call["server"]]:
                        if tool.name != tool_call["tool"]:
                            continue
                        try:
                            if self._logger is not None:
                                self._logger.info(
                                    "Executing tool %s of server %s", tool_call["tool"], tool_call["server"])
                                self._logger.info("With arguments: %s", str(tool_call["arguments"]))
                            # Execute tool with permission checking
                            response = await self._mcp_clients[tool_call["server"]].execute_tool(
                                tool_call["tool"], tool_call["arguments"], callbacks=callbacks)
                            t.add({
                                "type": "tool",
                                "class": self.__class__.__name__,
                                "server": tool_call["server"],
                                "tool_name": tool_call["tool"],
                                "arguments": tool_call["arguments"],
                                "response": response.model_dump(mode="json")
                                if isinstance(response, BaseModel) else response,
                                "error": ""
                            })
                            return response
                        except Exception as e:
                            t.add({
                                "type": "tool",
                                "class": self.__class__.__name__,
                                "tool_name": tool_call["tool"],
                                "arguments": tool_call["arguments"],
                                "response": "",
                                "error": str(e)
                            })
                            raise RuntimeError(f"Error occurred during executing tool {tool_call['tool']}") from e
                    raise RuntimeError(f"Server {tool_call['server']} has no tool {tool_call['tool']}")
                raise RuntimeError("The input of `call_tool` function has a wrong format")
            except json.JSONDecodeError as e:
                t.add({
                    "type": "tool",
                    "class": self.__class__.__name__,
                    "tool_name": tool_call["tool"],
                    "arguments": tool_call["arguments"],
                    "response": "",
                    "error": str(e)
                })
                raise RuntimeError("Failed to parse the input of `call_tool` function") from e

    @property
    def initialized(self) -> bool:
        """Check if the agent is initialized."""
        return self._initialized

    @property
    def name(self) -> str:
        """Return agent name."""
        return self._name

    def set_name(self, name: str):
        """Set a name."""
        self._name = name
        self._config.name = name

    @property
    def id(self) -> str:
        """Return agent ID."""
        if self._project_id:
            return f"{self._project_id}:agent:{self._name}"
        return f"agent:{self._name}"

    def set_project_id(self, project_id: str):
        """Set project ID."""
        self._project_id = project_id

    def list_undefined_env_vars(self, **kwargs) -> List[str]:
        """
        Return a list of undefined environment variables used in this agent.

        Returns:
            List[str]: A list of undefined environment variables.
        """
        undefined_vars = []
        if self._mcp_manager is None:
            return undefined_vars
        params = self._mcp_manager.list_unspecified_params()
        for server in self._config.servers:
            names = params.get(server["name"])
            if names:
                undefined_vars.extend([name.strip("{{").strip("}}").strip() for name in names])
        return undefined_vars

    def set_context(self, context: Context):
        """
        Set context, e.g., environment variables (API keys).
        """
        if context and self._llm:
            self._llm.set_context(context)

    def get_children_ids(self) -> List[str]:
        """
        Return the MCP client IDs in this agent.

        Returns:
            List[str]: A list of MCP client IDs.
        """
        ids = [client.id for _, client in self._mcp_clients.items()]
        return ids

    def get_mcp_configs(self) -> Dict[str, Dict[str, Any]]:
        """
        Retrieve MCP configurations from all connected clients.
        
        Returns:
            Dict[str, Dict[str, Any]]: A dictionary mapping server names to their
            MCP configurations.
        """
        configs = {}
        for name, client in self._mcp_clients.items():
            config = client.get_mcp_config()
            if config:
                configs[name] = config
        return configs

    def get_remote_mcp_list(self) -> List[Dict[str, str]]:
        """
        Return tool configurations for remote MCP servers.
        The output format follows OpenAI Responses API.

        Returns:
            List[Dict[str, str]]: A list of tool configurations.
        """
        if self._config.use_llm_tool_api.lower() == "no":
            return []

        tools = []
        if (self._config.mcp_gateway_url and
                "localhost" not in self._config.mcp_gateway_url and
                "127.0.0.1" not in self._config.mcp_gateway_url):
            for server_name in self._tools:
                tools.append({
                    "type": "mcp",
                    "server_label": server_name,
                    "server_url": f"{self._config.mcp_gateway_url}/{server_name}/sse",
                    "require_approval": "never",
                })
        return tools

    def get_callable_tool_list(self) -> List[Dict[str, str]]:
        """
        Return a list of callable tools used by this agent.
        The output format follows OpenAI Responses API.

        Returns:
            List[Dict[str, str]]: A list of tool configurations.
        """
        if self._config.use_llm_tool_api.lower() == "no":
            return []

        tools = []
        for server_name, tool_configs in self._tools.items():
            for tool in tool_configs:
                tools.append({
                    "type": "function",
                    "name": f"{server_name}.{tool.name}",
                    "description": tool.description,
                    "parameters": tool.inputSchema
                })
        return tools
