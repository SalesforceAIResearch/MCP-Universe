"""
This module provides the MCPManager class for managing MCP (Model Control Protocol) servers.

The MCPManager class is responsible for loading and managing server configurations,
setting parameters, and building clients for MCP servers. It supports both stdio
and SSE (Server-Sent Events) transport types.
"""
# pylint: disable=broad-exception-caught
import os
import json
from typing import Dict, List, Union
from dotenv import load_dotenv
from mcpworld.common.misc import AutodocABCMeta
from mcpworld.common.logger import get_logger
from .config import ServerConfig
from .client import MCPClient

load_dotenv()


class MCPManager(metaclass=AutodocABCMeta):
    """
    Manages MCP (Model Control Protocol) servers.

    This class is responsible for loading server configurations, setting parameters,
    and building clients for MCP servers. It supports both stdio and SSE (Server-Sent Events)
    transport types.

    Attributes:
        _server_configs (Dict[str, ServerConfig]): A dictionary of server configurations.
        _logger: Logger instance for this class.
    """

    def __init__(self, config: Union[str, Dict] = None):
        """
        Initializes an MCPManager instance.

        Args:
            config (Union[str, Dict], optional): The configuration file path or a dictionary
                containing server configurations. If None, the default configuration file
                will be used.
        """
        self._server_configs: Dict[str, ServerConfig] = {}
        self._logger = get_logger(self.__class__.__name__)
        self.load_configs(config)
        # Set params defined in the environment variables
        for name in self._server_configs:
            self.set_params(server_name=name, params=None)

    def load_configs(self, config: Union[str, Dict] = None):
        """
        Loads server configurations from a file or dictionary.

        Args:
            config (Union[str, Dict], optional): The configuration file path or a dictionary
                containing server configurations. If None, the default configuration file
                will be used.

        Raises:
            FileNotFoundError: If the specified configuration file does not exist.
            ValueError: If there are duplicate server names in the configuration.
            Exception: If there's an error loading a server's configuration.

        Note:
            If a configuration fails to load for a specific server, a fatal log message
            will be recorded, but the method will continue loading other configurations.
        """

        def _raise_on_duplicates(ordered_pairs):
            """Reject duplicate server names"""
            d = {}
            for k, v in ordered_pairs:
                if k in d:
                    raise ValueError(f"Duplicate server name: {k}")
                d[k] = v
            return d

        if isinstance(config, dict):
            configs = config
        else:
            if config is None or config == "":
                folder = os.path.dirname(os.path.realpath(__file__))
                config = os.path.join(folder, "configs/server_list.json")
            assert os.path.isfile(config), f"File `{config}` does not exist"
            with open(config, "r", encoding="utf-8") as f:
                configs = json.load(f, object_pairs_hook=_raise_on_duplicates)

        self._server_configs = {}
        for name, conf in configs.items():
            try:
                self._server_configs[name] = ServerConfig.from_dict(conf)
            except Exception as e:
                self._logger.fatal("Failed to load config of server `%s`: %s", name, str(e))

    def set_params(self, server_name: str, params: Dict = None):
        """
        Sets parameters for a specific server.

        Args:
            server_name (str): The name of the server to set parameters for.
            params (Dict, optional): A dictionary of parameters to set. If None,
                only environment variables will be applied.
        """
        assert server_name in self._server_configs, f"Unknown server: {server_name}"
        self._server_configs[server_name].render_template(params=params)

    def list_unspecified_params(self) -> Dict[str, List[str]]:
        """
        Lists parameters with unspecified values for all servers.

        Returns:
            Dict[str, List[str]]: A dictionary where keys are server names and values
                are lists of unspecified parameter names for each server.
        """
        unspecified_params = {}
        for name, config in self._server_configs.items():
            params = config.list_unspecified_params()
            if params:
                unspecified_params[name] = params
        return unspecified_params

    def get_configs(self) -> Dict[str, ServerConfig]:
        """
        Retrieves all server configurations.

        Returns:
            Dict[str, ServerConfig]: A dictionary of all server configurations,
                where keys are server names and values are ServerConfig objects.
        """
        return self._server_configs

    def get_config(self, name: str) -> ServerConfig:
        """
        Retrieves the configuration for a specific server.

        Args:
            name (str): The name of the server.

        Returns:
            ServerConfig: The configuration object for the specified server.
        """
        if name not in self._server_configs:
            raise RuntimeError(f"Unknown server: {name}")
        return self._server_configs[name]

    async def build_client(
            self,
            server_name: str,
            transport: str = "stdio",
            timeout: int = 30
    ) -> MCPClient:
        """
        Builds and returns an MCP client for a specified server.

        Args:
            server_name (str): The name of the MCP server to connect to.
            transport (str, optional): The transport type, either "stdio" or "sse". Defaults to "stdio".
            timeout (int, optional): Connection timeout in seconds. Defaults to 30.

        Returns:
            MCPClient: An MCP client connected to the specified server.

        Note:
            For SSE transport, the MCP_GATEWAY_ADDRESS environment variable must be set.
        """
        assert transport in ["stdio", "sse"], "Transport type should be `stdio` or `sse`"
        assert server_name in self._server_configs, f"Unknown server: {server_name}"
        server_config = self._server_configs[server_name]
        if transport == "stdio":
            if server_config.stdio.list_unspecified_params():
                raise RuntimeError(f"Server {server_name} has unspecified parameters: "
                                   f"{server_config.list_unspecified_params()}")
        else:
            if server_config.sse.command == "":
                raise RuntimeError(f"Server {server_name} does not support SSE")

        client = MCPClient(name=f"{server_name}_client")
        if transport == "stdio":
            await client.connect_to_stdio_server(server_config, timeout=timeout)
        else:
            gateway_address = os.environ.get("MCP_GATEWAY_ADDRESS", "")
            if gateway_address == "":
                raise ValueError("MCP_GATEWAY_ADDRESS is not set")
            await client.connect_to_sse_server(f"{gateway_address}/{server_name}/sse")
        return client
