# Adding MCP Servers to MCPUniverse

This guide explains how to add new Model Control Protocol (MCP) servers to the MCPUniverse framework. There are three main approaches: creating custom Python MCP servers, integrating existing third-party servers, and connecting to remote MCP servers.

## Overview

MCPUniverse uses a centralized server configuration system that manages different types of MCP servers. All server configurations are stored in `mcpuniverse/mcp/configs/server_list.json`, which defines how to launch, connect to, and manage each server.

## 1. Adding Custom Python MCP Servers

### Step 1: Create Your Server Implementation

Create a new directory in `mcpuniverse/mcp/servers/` for your server:

```bash
mkdir mcpuniverse/mcp/servers/my_custom_server
```

Create the server implementation files:

**mcpuniverse/mcp/servers/my_custom_server/server.py:**
```python
"""
A custom MCP server implementation
"""
import click
from typing import Any
from mcp.server.fastmcp import FastMCP
from mcpuniverse.common.logger import get_logger


def build_server(port: int) -> FastMCP:
    """
    Initialize the MCP server.
    
    Args:
        port: Port for SSE transport
        
    Returns:
        The configured MCP server
    """
    mcp = FastMCP("my-custom-server", port=port)
    logger = get_logger("my-custom-server")
    
    @mcp.tool()
    async def my_custom_tool(param1: str, param2: int = 10) -> str:
        """
        Description of what this tool does.
        
        Args:
            param1: Description of parameter 1
            param2: Description of parameter 2 (optional)
            
        Returns:
            Result description
        """
        logger.info(f"Executing custom tool with {param1} and {param2}")
        
        # Your custom logic here
        result = f"Processed {param1} with value {param2}"
        return result
    
    @mcp.tool()
    async def another_tool(data: dict) -> dict:
        """Another tool that processes dictionary data."""
        return {"processed": True, "original": data}
    
    @mcp.resource("custom://data/{resource_id}")
    def get_custom_resource(resource_id: str) -> str:
        """Get a custom resource by ID."""
        return f"Resource data for {resource_id}"
    
    return mcp


@click.command()
@click.option(
    "--transport",
    type=click.Choice(["stdio", "sse"]),
    default="stdio",
    help="Transport type"
)
@click.option("--port", default="8000", help="Port to listen on for SSE")
def main(transport: str, port: str):
    """Start the MCP server."""
    logger = get_logger("my-custom-server")
    logger.info("Starting my custom MCP server")
    
    mcp = build_server(int(port))
    mcp.run(transport=transport.lower())


if __name__ == "__main__":
    main()
```

**mcpuniverse/mcp/servers/my_custom_server/__init__.py:**
```python
"""My Custom MCP Server"""
```

**mcpuniverse/mcp/servers/my_custom_server/__main__.py:**
```python
import sys
from .server import main

sys.exit(main())
```

### Step 2: Register Your Server

Add your server configuration to `mcpuniverse/mcp/configs/server_list.json`:

```json
{
  "my-custom-server": {
    "stdio": {
      "command": "python3",
      "args": [
        "-m", "mcpuniverse.mcp.servers.my_custom_server"
      ]
    },
    "sse": {
      "command": "python3", 
      "args": [
        "-m", "mcpuniverse.mcp.servers.my_custom_server",
        "--transport", "sse",
        "--port", "{{PORT}}"
      ]
    },
    "env": {
      "CUSTOM_API_KEY": "{{CUSTOM_API_KEY}}",
      "CUSTOM_CONFIG": "{{CUSTOM_CONFIG_PATH}}"
    }
  }
}
```

### Step 3: Create Tests

Create test files in `tests/mcp/servers/my_custom_server/`:

**tests/mcp/servers/my_custom_server/test_my_custom_server.py:**
```python
import unittest
from mcpuniverse.mcp.servers.my_custom_server.server import build_server


class TestMyCustomServer(unittest.IsolatedAsyncioTestCase):
    
    def setUp(self):
        self.server = build_server(port=12345)
    
    async def test_server_tools(self):
        tools = await self.server.list_tools()
        tool_names = [tool.name for tool in tools]
        
        self.assertIn("my_custom_tool", tool_names)
        self.assertIn("another_tool", tool_names)
    
    async def test_my_custom_tool(self):
        result = await self.server.call_tool("my_custom_tool", {
            "param1": "test",
            "param2": 42
        })
        self.assertIn("Processed test with value 42", str(result))


if __name__ == "__main__":
    unittest.main()
```

### Step 4: Usage in Agents

Use your server in agent configurations:

**agent_config.yaml:**
```yaml
name: "test-agent"
instruction: "An agent that uses my custom server"
servers:
  - name: "my-custom-server"
  - name: "weather"  # Can combine with other servers
```

## 2. Adding Existing Third-Party MCP Servers

### NPM/Node.js Packages

For servers published as NPM packages, add them directly to the configuration:

```json
{
  "third-party-server": {
    "stdio": {
      "command": "npx",
      "args": [
        "-y",
        "package-name-from-npm"
      ]
    },
    "env": {
      "API_KEY": "{{THIRD_PARTY_API_KEY}}"
    }
  }
}
```

**Example with actual third-party servers:**
```json
{
  "github": {
    "stdio": {
      "command": "npx", 
      "args": [
        "-y",
        "@modelcontextprotocol/server-github"
      ]
    },
    "env": {
      "GITHUB_PERSONAL_ACCESS_TOKEN": "{{GITHUB_PERSONAL_ACCESS_TOKEN}}"
    }
  },
  
  "filesystem": {
    "stdio": {
      "command": "npx",
      "args": [
        "-y", 
        "@modelcontextprotocol/server-filesystem",
        "{{FILESYSTEM_DIRECTORY}}"
      ]
    }
  }
}
```

### Python Packages

For Python packages available via pip:

```json
{
  "python-third-party": {
    "stdio": {
      "command": "python3",
      "args": [
        "-m", "third_party_package_name"
      ]
    },
    "env": {
      "PACKAGE_CONFIG": "{{PACKAGE_CONFIG_PATH}}"
    }
  }
}
```

**Example:**
```json
{
  "calculator": {
    "stdio": {
      "command": "python3",
      "args": [
        "-m", "mcp_server_calculator"
      ]
    }
  },
  
  "fetch": {
    "stdio": {
      "command": "python3", 
      "args": [
        "-m", "mcp_server_fetch",
        "--ignore-robots-txt"
      ]
    }
  }
}
```

### Binary Executables

For servers distributed as binaries:

```json
{
  "binary-server": {
    "stdio": {
      "command": "/path/to/binary",
      "args": [
        "--config", "{{CONFIG_PATH}}",
        "--mode", "stdio"
      ]
    },
    "sse": {
      "command": "/path/to/binary",
      "args": [
        "--config", "{{CONFIG_PATH}}",
        "--mode", "sse", 
        "--port", "{{PORT}}"
      ]
    }
  }
}
```

## 3. Adding Remote MCP Servers

Using MCP remote proxy:

```json
{
  "proxied-remote": {
    "stdio": {
      "command": "npx",
      "args": [
        "mcp-remote", 
        "https://remote-mcp-server.com/sse"
      ]
    }
  }
}
```

## Environment Variables and Configuration

### Setting Environment Variables

Create a `.env` file in your project root:

```bash
# Third-party API keys
GITHUB_PERSONAL_ACCESS_TOKEN=your_github_token_here
GOOGLE_MAPS_API_KEY=your_google_maps_key
SERP_API_KEY=your_serp_api_key

# Custom server configurations
CUSTOM_API_KEY=your_custom_api_key
FILESYSTEM_DIRECTORY=/path/to/allowed/directory

# Remote server authentication
REMOTE_API_TOKEN=your_remote_token
```

### Template Variables

The server configuration supports template variables that are replaced at runtime:

- `{{PORT}}`: Automatically assigned port for SSE transport
- Any environment variable in `{{VARIABLE_NAME}}` format

## Usage Examples

### Basic Server Usage

```python
from mcpuniverse.mcp.manager import MCPManager
from mcpuniverse.agent.manager import AgentManager
from mcpuniverse.llm.manager import ModelManager

# Initialize components
mcp_manager = MCPManager()
llm = ModelManager().build_model(name="openai")
agent_manager = AgentManager()

# Create agent with your custom server
agent = agent_manager.build_agent(
    class_name="function_call",
    mcp_manager=mcp_manager,
    llm=llm,
    config={
        "name": "test-agent",
        "instruction": "Use custom tools to solve problems",
        "servers": [
            {"name": "my-custom-server"},
            {"name": "weather"}
        ]
    }
)

# Use the agent
await agent.initialize()
response = await agent.execute("Use my custom tool with some data")
await agent.cleanup()
```

### Programmatic Server Management

```python
from mcpuniverse.mcp.manager import MCPManager

manager = MCPManager()

# Build client for specific server
client = await manager.build_client("my-custom-server", transport="stdio")
# List available tools
tools = await client.list_tools()
print(f"Available tools: {tools}")
# Execute a tool
result = await client.execute_tool("my_custom_tool", {
    "param1": "hello",
    "param2": 123
})
print(f"Tool result: {result}")
await client.cleanup()
```

### Dynamic Server Registration

Register servers dynamically at runtime:

```python
manager = MCPManager()

# Add server configuration dynamically
new_server_config = {
    "stdio": {
        "command": "python3",
        "args": ["-m", "my.dynamic.server"]
    }
}

manager.add_server_config("dynamic-server", new_server_config)
```

## Troubleshooting

### Common Issues

1. **Server Not Found**: Ensure the server name in `server_list.json` matches what you use in agent configs
2. **Command Not Found**: Verify the command and arguments are correct and the package is installed
3. **Environment Variables**: Check that all required environment variables are set in `.env` or your environment
4**Permission Issues**: Verify file permissions for binary executables

### Debugging

Enable debug logging:

```python
import logging
logging.basicConfig(level=logging.DEBUG)

from mcpuniverse.mcp.manager import MCPManager
manager = MCPManager()
```

Test server connectivity:

```python
# Test if server can be reached
client = await manager.build_client("server-name")
try:
    tools = await client.list_tools()
    print(f"Success! Tools: {tools}")
except Exception as e:
    print(f"Failed to connect: {e}")
finally:
    await client.cleanup()
```

## Best Practices

1. **Documentation**: Document your tools with clear descriptions and parameter types
2. **Error Handling**: Implement proper error handling in your server tools
3. **Testing**: Write comprehensive tests for your server functionality
4. **Security**: Never hardcode API keys; always use environment variables
5. **Performance**: Consider async operations for I/O bound tasks
6. **Logging**: Use structured logging for debugging and monitoring
7. **Versioning**: Version your custom servers and maintain backward compatibility
8. **Resource Management**: Properly clean up resources in your server implementation

This guide provides a comprehensive overview of adding MCP servers to MCPUniverse. Choose the approach that best fits your use case, and refer to the existing server implementations in the codebase for additional examples and patterns.