"""
Base classes for agents
"""
# pylint: disable=broad-exception-caught
import os
import uuid
import json
from abc import abstractmethod
from typing import List, Any, Dict, Union, Optional, Literal
from dataclasses import dataclass, field
from collections import OrderedDict

from mcpworld.common.config import BaseConfig
from mcpworld.common.misc import ComponentABCMeta, ExportConfigMixin
from mcpworld.mcp.manager import MCPManager, MCPClient
from mcpworld.llm.base import BaseLLM
from mcpworld.tracer import Tracer
from mcpworld.agent.types import AgentResponse

DEFAULT_CONFIG_FOLDER = os.path.join(os.path.dirname(os.path.realpath(__file__)), "configs")
OUTPUT_FORMAT_PROMPT = """
Return your response in the following JSON structure:
{output_format}

You must respond with valid JSON only, with no triple backticks. No markdown formatting.
No extra text. Do not wrap in ```json code fences. Property names must be enclosed in double quotes.
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
        servers (List[Dict]): List of server configurations.
        resources (List[str]): List of resource identifiers.
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
    # A list of servers: [{"name": server_name}, {"name": server_name, "transport": "sse"}]
    servers: List[Dict[Literal["name", "transport", "tools"], str | list]] = field(default_factory=list)
    # A list of resources
    resources: List[str] = field(default_factory=list)


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
        self._name: str = self._config.name if self._config.name else str(uuid.uuid4())
        self._config.name = self._name
        self._mcp_manager: MCPManager = mcp_manager
        self._llm: BaseLLM = llm
        self._mcp_clients: Dict[str, MCPClient] = OrderedDict()
        self._tools: Dict[str, Any] = {}
        self._logger = None
        self._initialized: bool = False

    async def _initialize(self):
        """Initialize subclass."""

    async def initialize(self):
        """
        Initialize MCP clients and other resources.

        This method sets up the agent by creating MCP clients for each configured
        server and retrieving the available tools. It should be called before
        any execution takes place.

        Raises:
            RuntimeError: If initialization fails for any reason.
        """
        if self._initialized:
            return
        # Initialize MCP clients
        self._mcp_clients = OrderedDict()
        for server in self._config.servers:
            server_name = server["name"]
            client = await self._mcp_manager.build_client(
                server_name, transport=server.get("transport", "stdio"))
            self._mcp_clients[server_name] = client
        # Get the tools information
        self._tools = {}
        for server in self._config.servers:
            server_name = server["name"]
            tools = await self._mcp_clients[server_name].list_tools()
            selected_tools = server.get("tools", None)
            if selected_tools is None:
                self._tools[server_name] = tools
            else:
                self._tools[server_name] = [tool for tool in tools if tool.name in selected_tools]
        await self._initialize()
        self._initialized = True

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
            try:
                response = await self._execute(message, tracer=tracer, **kwargs)
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
                raise e
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

    async def call_tool(self, llm_response: Union[str, Dict]):
        """
        Call a specific tool indicated in a LLM response.

        This method parses the LLM response, identifies the tool to be called,
        and executes it using the appropriate MCP client.

        Args:
            llm_response (Union[str, Dict]): The response from the language model,
                                             either as a JSON string or a dictionary.

        Returns:
            Any: The result of the tool execution.

        Raises:
            RuntimeError: If the tool call fails for any reason (e.g., invalid format,
                          server not found, tool not found).
            json.JSONDecodeError: If the input string cannot be parsed as JSON.
        """
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
                            self._logger.info("Executing tool %s of server %s", tool_call["tool"], tool_call["server"])
                            self._logger.info("With arguments: %s", str(tool_call["arguments"]))
                        return await self._mcp_clients[tool_call["server"]].execute_tool(
                            tool_call["tool"], tool_call["arguments"])
                    except Exception as e:
                        raise RuntimeError(f"Error occurred during executing tool {tool_call['tool']}") from e
                raise RuntimeError(f"Server {tool_call['server']} has no tool {tool_call['tool']}")
            raise RuntimeError("The input of `call_tool` function has a wrong format")
        except json.JSONDecodeError as e:
            raise RuntimeError("Failed to parse the input of `call_tool` function") from e

    @property
    def name(self) -> str:
        """Return agent name."""
        return self._name

    @property
    def initialized(self) -> bool:
        """Check if the agent is initialized."""
        return self._initialized

    def set_name(self, name: str):
        """Set a name."""
        self._name = name
        self._config.name = name
