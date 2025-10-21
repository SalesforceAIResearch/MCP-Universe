"""
An MCP server for sending emails via HTTP POST
"""
from typing import Union, Any
import httpx
import click
from mcp.server.fastmcp import FastMCP
from mcpuniverse.common.logger import get_logger


def build_server(port: int) -> FastMCP:
    """
    Initializes the MCP server.

    :param port: Port for SSE.
    :return: The MCP server.
    """
    mcp = FastMCP("email", port=port)

    @mcp.tool()
    async def send_email(recipient: str, subject: str, body: str, sender: str = "agent@mcpuniverse.com") -> str:
        """
        Send an email by posting to localhost:8080/email.

        Args:
            recipient: Email address of the recipient
            subject: Subject line of the email
            body: Body content of the email
            sender: Email address of the sender (optional, defaults to agent@mcpuniverse.com)
        """
        email_data = {
            "recipient": recipient,
            "subject": subject,
            "body": body,
            "sender": sender
        }
        
        async with httpx.AsyncClient() as client:
            try:
                response = await client.post(
                    "http://localhost:8080/email",
                    json=email_data,
                    timeout=30.0
                )
                response.raise_for_status()
                result = response.json()
                return f"Email sent successfully. Status: {result.get('status', 'unknown')}, ID: {result.get('email_id', 'N/A')}"
            except httpx.HTTPStatusError as e:
                return f"Failed to send email. HTTP error: {e.response.status_code} - {e.response.text}"
            except httpx.RequestError as e:
                return f"Failed to send email. Request error: {str(e)}"
            except Exception as e:
                return f"Failed to send email. Error: {str(e)}"

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
    logger = get_logger("Service:email")
    logger.info("Starting the MCP server")
    mcp = build_server(int(port))
    mcp.run(transport=transport.lower())
