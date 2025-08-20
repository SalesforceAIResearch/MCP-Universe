"""
An echo server
"""
import click
from mcp.server.fastmcp import FastMCP
from mcpuniverse.common.logger import get_logger


def build_server(port: int) -> FastMCP:
    """
    Initializes the MCP server.

    :param port: Port for SSE.
    :return: The MCP server.
    """
    mcp = FastMCP("echo", port=port)

    @mcp.tool()
    def echo_tool(text: str) -> str:
        """Echo the input text"""
        return text

    @mcp.resource("echo://static")
    def echo_resource() -> str:
        return "Echo!"

    @mcp.resource("echo://{text}")
    def echo_template(text: str) -> str:
        """Echo the input text"""
        return f"Echo: {text}"

    @mcp.prompt("echo")
    def echo_prompt(text: str) -> str:
        return text

    return mcp


@click.command()
@click.option(
    "--transport",
    type=click.Choice(["stdio", "sse"]),
    default="stdio",
    help="Transport type",
)
@click.option("--port", default="8000", help="Port to listen on for SSE")
def main(transport: str, port: str):
    """
    Starts the initialized MCP server.

    :param port: Port for SSE.
    :param transport: The transport type, e.g., `stdio` or `sse`.
    :return:
    """
    assert transport.lower() in ["stdio", "sse"], \
        "Transport should be `stdio` or `sse`"
    logger = get_logger("Service:echo")
    logger.info("Starting the MCP server")
    mcp = build_server(int(port))
    mcp.run(transport=transport.lower())
