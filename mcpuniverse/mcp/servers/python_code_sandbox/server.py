"""MCP server for executing Python code in a secure Docker sandbox."""
import asyncio
import os
import click
import requests
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
    mcp = FastMCP("python-code-sandbox", port=port)
    logger = get_logger("python-code-sandbox")

    @mcp.tool()
    async def execute_python_code(code: str):

        """
        Execute Python code in a secure Docker sandbox, you can ONLY use the
        following packages: numpy, pandas, scipy, sklearn, sympy. 
        - The code should be runnable on its own.
        - The code should print the intermediate results and the final results.
        - The code should throw a timeout error if it takes more than 300 seconds.
        
        Args:
            code: Python code to execute
            
        Returns:
            result: Result of the code execution
        """
        # You'll need to define these - they're referenced but not defined
        host_port = int(os.environ.get("SANDBOX_HOST_PORT", "18080"))
        address = os.environ.get("SANDBOX_ADDRESS", "localhost")
        container_url = f"http://{address}:{host_port}"
        timeout = 300

        api_key = os.environ.get("SANDBOX_API_KEY", "")
        headers = {}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"

        try:
            # Use requests.post instead of aiohttp
            # Run in thread pool to avoid blocking the event loop
            response = await asyncio.to_thread(
                requests.post,
                f"{container_url}/execute",
                json={"code": code, "timeout": timeout},
                headers=headers,
                timeout=timeout + 10
            )

            if response.status_code == 200:
                result = response.json()
                return result
            return {
                "success": False,
                "exit_code": -1,
                "output": "",
                "error": f"HTTP error {response.status_code}: {response.text}"
            }

        except requests.exceptions.Timeout:
            return {
                "success": False,
                "exit_code": -1,
                "output": "",
                "error": f"Request timeout after {timeout} seconds"
            }
        except Exception as e:  # pylint: disable=broad-exception-caught
            logger.error("Code execution error: %s", e)
            return {
                "success": False,
                "exit_code": -1,
                "output": "",
                "error": f"Execution error: {str(e)}"
            }

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
    logger = get_logger("python-code-sandbox")
    logger.info("Starting python sandbox")

    mcp = build_server(int(port))
    mcp.run(transport=transport.lower())


if __name__ == "__main__":
    main()  # pylint: disable=no-value-for-parameter
