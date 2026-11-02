"""
Ref: MiroThinker jina_scrape_llm_summary
  github.com/MiroMindAI/MiroThinker/blob/main/libs/miroflow-tools/
  src/miroflow_tools/dev_mcp_servers/jina_scrape_llm_summary.py
"""
# pylint: disable=too-many-statements,too-many-branches,too-many-return-statements
# pylint: disable=broad-exception-caught,global-statement,invalid-name

import asyncio
import json
import os
import subprocess
import sys
from typing import Any, Dict

import click
import httpx
from mcp.server.fastmcp import FastMCP

from mcpuniverse.common.logger import get_logger

SUMMARY_LLM_BASE_URL = os.environ.get("SUMMARY_LLM_BASE_URL")
SUMMARY_LLM_MODEL_NAME = os.environ.get("SUMMARY_LLM_MODEL_NAME")
SUMMARY_LLM_API_KEY = os.environ.get("SUMMARY_LLM_API_KEY")

JINA_API_KEY = os.environ.get("JINA_API_KEY", "")
JINA_BASE_URL = os.environ.get("JINA_BASE_URL", "https://r.jina.ai")


def build_server(port: int) -> FastMCP:
    """
    Initialize the MCP server.
    
    Args:
        port: Port for SSE transport
        
    Returns:
        The configured MCP server
    """
    mcp = FastMCP("jina_scrape_llm_summary", port=port)

    @mcp.tool()
    async def scrape_and_extract_info(
        url: str, info_to_extract: str, custom_headers: Dict[str, str] = None
    ) -> Dict[str, Any]:
        """
        Scrape content from a URL, including web pages, PDFs, code files, 
        and other supported resources, and extract meaningful information using an LLM.
        If you need to extract information from a PDF, please use this tool.

        Args:
            url (str): The URL to scrape content from. Supports various types of URLs
            such as web pages, PDFs, raw text/code files (e.g., GitHub, Gist), and similar sources.
            info_to_extract (str): The specific types of information to extract (usually a question)
            custom_headers (Dict[str, str]): Additional headers to include in the scraping request

        Returns:
            Dict[str, Any]: A dictionary containing:
                - success (bool): Whether the operation was successful
                - url (str): The original URL
                - extracted_info (str): The extracted information
                - error (str): Error message if the operation failed
                - scrape_stats (Dict): Statistics about the scraped content
                - model_used (str): The model used for summarization
                - tokens_used (int): Number of tokens used (if available)
        """
        if _is_huggingface_dataset_or_space_url(url):
            return {
                "success": False,
                "url": url,
                "extracted_info": "",
                "error": (
                    "You are trying to scrape a Hugging Face dataset for answers, "
                    "please do not use the scrape tool for this purpose."
                ),
                "scrape_stats": {},
                "tokens_used": 0,
            }

        # First, scrape the content
        scrape_result = await scrape_url_with_jina(url, custom_headers)

        if not scrape_result["success"]:
            print(
                f"Jina Scrape and Extract Info: Scraping failed: {scrape_result['error']}", file=sys.stderr
            )
            return {
                "success": False,
                "url": url,
                "extracted_info": "",
                "error": f"Scraping failed: {scrape_result['error']}",
                "scrape_stats": {},
                "tokens_used": 0,
            }

        # Then, summarize the content
        extracted_result = await extract_info_with_llm(
            url=url,
            content=scrape_result["content"],
            info_to_extract=info_to_extract,
            model=SUMMARY_LLM_MODEL_NAME,
            max_tokens=8192,
        )

        # Combine results
        return {
            "success": extracted_result["success"],
            "url": url,
            "extracted_info": extracted_result["extracted_info"],
            "error": extracted_result["error"],
            "scrape_stats": {
                "line_count": scrape_result["line_count"],
                "char_count": scrape_result["char_count"],
                "last_char_line": scrape_result["last_char_line"],
                "all_content_displayed": scrape_result["all_content_displayed"],
            },
            "model_used": extracted_result["model_used"],
            "tokens_used": extracted_result["tokens_used"],
        }


    def _is_huggingface_dataset_or_space_url(url):
        """
        Check if the URL is a HuggingFace dataset or space URL.
        :param url: The URL to check
        :return: True if it's a HuggingFace dataset or space URL, False otherwise
        """
        if not url:
            return False
        return "huggingface.co/datasets" in url or "huggingface.co/spaces" in url


    async def scrape_url_with_jina(
        url: str, custom_headers: Dict[str, str] = None, max_chars: int = 102400 * 4
    ) -> Dict[str, Any]:
        """
        Scrape content from a URL and save to a temporary file. Need to read the content from the temporary file.


        Args:
            url (str): The URL to scrape content from
            custom_headers (Dict[str, str]): Additional headers to include in the request
            max_chars (int): Maximum number of characters to reserve for the scraped content

        Returns:
            Dict[str, Any]: A dictionary containing:
                - success (bool): Whether the operation was successful
                - filename (str): Absolute path to the temporary file containing the scraped content
                - content (str): The scraped content of the first 40k characters
                - error (str): Error message if the operation failed
                - line_count (int): Number of lines in the scraped content
                - char_count (int): Number of characters in the scraped content
                - last_char_line (int): Line number where the last displayed char is
                - all_content_displayed (bool): True if content <= 40k chars
        """

        # Validate input
        if not url or not url.strip():
            return {
                "success": False,
                "filename": "",
                "content": "",
                "error": "URL cannot be empty",
                "line_count": 0,
                "char_count": 0,
                "last_char_line": 0,
                "all_content_displayed": False,
            }

        # Get API key from environment
        if not JINA_API_KEY:
            return {
                "success": False,
                "filename": "",
                "content": "",
                "error": "JINA_API_KEY environment variable is not set",
                "line_count": 0,
                "char_count": 0,
                "last_char_line": 0,
                "all_content_displayed": False,
            }

        # Construct the Jina.ai API URL
        jina_url = f"{JINA_BASE_URL}/{url}"

        try:
            # Prepare headers
            headers = {
                "Authorization": f"Bearer {JINA_API_KEY}",
            }

            # Add custom headers if provided
            if custom_headers:
                headers.update(custom_headers)

            # Retry configuration
            retry_delays = [1, 2, 4, 8]

            for attempt, delay in enumerate(retry_delays, 1):
                try:
                    # Make the request using httpx library
                    async with httpx.AsyncClient() as client:
                        response = await client.get(
                            jina_url,
                            headers=headers,
                            timeout=httpx.Timeout(None, connect=20, read=60),
                            follow_redirects=True,  # Follow redirects (equivalent to curl -L)
                        )

                    # Check if request was successful
                    response.raise_for_status()
                    break  # Success, exit retry loop

                except httpx.ConnectTimeout as e:
                    # connection timeout, retry
                    if attempt < len(retry_delays):
                        delay = retry_delays[attempt]
                        print(
                            f"Jina Scrape: Connection timeout, {delay}s before next attempt (attempt {attempt + 1})",
                            file=sys.stderr
                        )
                        await asyncio.sleep(delay)
                        continue
                    print(
                        f"Jina Scrape: Connection retry attempts exhausted, url: {url}", file=sys.stderr
                    )
                    raise e

                except httpx.ConnectError as e:
                    # connection error, retry
                    if attempt < len(retry_delays):
                        delay = retry_delays[attempt]
                        print(
                            f"Jina Scrape: Connection error: {e}, {delay}s before next attempt", file=sys.stderr
                        )
                        await asyncio.sleep(delay)
                        continue
                    print(
                        f"Jina Scrape: Connection retry attempts exhausted, url: {url}", file=sys.stderr
                    )
                    raise e

                except httpx.ReadTimeout as e:
                    # read timeout, retry
                    if attempt < len(retry_delays):
                        delay = retry_delays[attempt]
                        print(
                            f"Jina Scrape: Read timeout, {delay}s before next attempt (attempt {attempt + 1})",
                            file=sys.stderr
                        )
                        await asyncio.sleep(delay)
                        continue
                    print(
                        f"Jina Scrape: Read timeout retry attempts exhausted, url: {url}", file=sys.stderr
                    )
                    raise e

                except httpx.HTTPStatusError as e:
                    if attempt < len(retry_delays):
                        print(
                            f"Jina Scrape: HTTP error: {e}, response.text: {response.text}, url: {url}, "
                            f"{delay}s before next attempt (attempt {attempt + 1})", file=sys.stderr
                        )
                        await asyncio.sleep(delay)
                        continue
                    print(
                        f"Jina Scrape: HTTP error retry attempts exhausted, url: {url}", file=sys.stderr
                    )
                    raise e

                except httpx.RequestError as e:
                    if attempt < len(retry_delays):
                        print(
                            f"Jina Scrape: Unknown request exception: {e}, url: {url}, "
                            f"{delay}s before next attempt (attempt {attempt + 1})", file=sys.stderr
                        )
                        await asyncio.sleep(delay)
                        continue
                    print(
                        f"Jina Scrape: Unknown request exception retry attempts exhausted, url: {url}", file=sys.stderr
                    )
                    raise e

        except Exception as e:
            error_msg = f"Jina Scrape: Unexpected error occurred: {str(e)}"
            print(error_msg, file=sys.stderr)
            return {
                "success": False,
                "filename": "",
                "content": "",
                "error": error_msg,
                "line_count": 0,
                "char_count": 0,
                "last_char_line": 0,
                "all_content_displayed": False,
            }

        # Get the scraped content
        content = response.text

        if not content:
            return {
                "success": False,
                "filename": "",
                "content": "",
                "error": "No content returned from Jina.ai API",
                "line_count": 0,
                "char_count": 0,
                "last_char_line": 0,
                "all_content_displayed": False,
            }

        # handle insufficient balance error
        try:
            content_dict = json.loads(content)
        except json.JSONDecodeError:
            content_dict = None
        if (
            isinstance(content_dict, dict)
            and content_dict.get("name") == "InsufficientBalanceError"
        ):
            return {
                "success": False,
                "filename": "",
                "content": "",
                "error": "Insufficient balance",
                "line_count": 0,
                "char_count": 0,
                "last_char_line": 0,
                "all_content_displayed": False,
            }

        # Get content statistics
        total_char_count = len(content)
        total_line_count = content.count("\n") + 1 if content else 0

        # Extract first max_chars characters
        displayed_content = content[:max_chars]
        all_content_displayed = total_char_count <= max_chars

        # Calculate the line number of the last character displayed
        if displayed_content:
            # Count newlines up to the last displayed character
            last_char_line = displayed_content.count("\n") + 1
        else:
            last_char_line = 0

        return {
            "success": True,
            "content": displayed_content,
            "error": "",
            "line_count": total_line_count,
            "char_count": total_char_count,
            "last_char_line": last_char_line,
            "all_content_displayed": all_content_displayed,
        }

    EXTRACT_INFO_PROMPT = (
        "You are given a piece of content and the requirement of "
        "information to extract. Your task is to extract the "
        "information specifically requested. Be precise and focus "
        "exclusively on the requested information.\n\n"
        "    INFORMATION TO EXTRACT:\n"
        "    {}\n\n"
        "    INSTRUCTIONS:\n"
        "    1. Extract the information relevant to the focus above.\n"
        "    2. If the exact information is not found, extract the most "
        "closely related details.\n"
        "    3. Be specific and include exact details when available.\n"
        "    4. Clearly organize the extracted information for easy "
        "understanding.\n"
        "    5. Do not include general summaries or unrelated content.\n\n"
        "    CONTENT TO ANALYZE:\n"
        "    {}\n\n"
        "    EXTRACTED INFORMATION:"
    )


    def get_prompt_with_truncation(
        info_to_extract: str, content: str, truncate_last_num_chars: int = -1
    ) -> str:
        if truncate_last_num_chars > 0:
            content = content[:-truncate_last_num_chars] + "[...truncated]"

        # Prepare the prompt
        prompt = EXTRACT_INFO_PROMPT.format(info_to_extract, content)
        return prompt


    async def extract_info_with_llm(
        url: str,
        content: str,
        info_to_extract: str,
        model: str = "LLM",
        max_tokens: int = 4096,
    ) -> Dict[str, Any]:
        """
        Summarize content using an LLM API.

        Args:
            content (str): The content to summarize
            info_to_extract (str): The specific types of information to extract (usually a question)
            model (str): The model to use for summarization
            max_tokens (int): Maximum tokens for the response

        Returns:
            Dict[str, Any]: A dictionary containing:
                - success (bool): Whether the operation was successful
                - extracted_info (str): The extracted information
                - error (str): Error message if the operation failed
                - model_used (str): The model used for summarization
                - tokens_used (int): Number of tokens used (if available)
        """

        # Validate input
        if not content or not content.strip():
            return {
                "success": False,
                "extracted_info": "",
                "error": "Content cannot be empty",
                "model_used": model,
                "tokens_used": 0,
            }

        prompt = get_prompt_with_truncation(info_to_extract, content)

        # Prepare the payload
        if "gpt" in model:
            payload = {
                "model": model,
                "max_completion_tokens": max_tokens,
                "messages": [
                    {"role": "user", "content": prompt},
                ],
            }
            if "5-mini" in model:
                payload["reasoning_effort"] = "minimal"
        elif "gemini" in model:
            # replace MODEL_ID in SUMMARY_LLM_BASE_URL to model
            global SUMMARY_LLM_BASE_URL
            SUMMARY_LLM_BASE_URL = SUMMARY_LLM_BASE_URL.replace("MODEL_ID", model)
            if "openrouter" in SUMMARY_LLM_BASE_URL: # openrouter
                payload = {
                    "model": model,
                    "max_tokens": max_tokens,
                    "messages": [
                        {"role": "user", "content": [{"type": "text", "text": prompt}]},
                    ],
                    # "temperature": 1.0,
                    "reasoning": {"max_tokens": 0, "enabled": False}
                }
            else: # vertex ai or google api
                payload = {
                    "contents": {
                        "role": "user",
                        "parts": [
                            {
                            "text": prompt
                            }
                        ]
                    },
                    "generationConfig": {
                        "maxOutputTokens": max_tokens,
                        "thinkingConfig": {
                                "thinkingBudget": 0
                            }
                    }
                }
        else:
            payload = {
                "model": model,
                "max_tokens": max_tokens,
                "messages": [
                    {"role": "user", "content": prompt},
                ],
                "temperature": 1.0,
                # "top_p": 0.8,
                # "top_k": 20,
            }

        # Validate LLM endpoint configuration early for clearer errors
        if not SUMMARY_LLM_BASE_URL or not SUMMARY_LLM_BASE_URL.strip():
            return {
                "success": False,
                "extracted_info": "",
                "error": "SUMMARY_LLM_BASE_URL environment variable is not set",
                "model_used": model,
                "tokens_used": 0,
            }

        # Prepare headers (add Authorization if API key is available)
        headers = {"Content-Type": "application/json"}
        # print(SUMMARY_LLM_API_KEY)
        if SUMMARY_LLM_API_KEY:
            if "generativelanguage.googleapis" in SUMMARY_LLM_BASE_URL: # google api
                headers["x-goog-api-key"] = SUMMARY_LLM_API_KEY
            elif "gemini" in model and "openrouter" not in SUMMARY_LLM_BASE_URL: # vertex ai
                gemini_api_key = subprocess.check_output(
                    ["gcloud", "auth", "application-default", "print-access-token"]
                ).decode().strip()
                headers["Authorization"] = f"Bearer {gemini_api_key}"
            else: # openrouter and openai
                # using openai API, use Authorization header
                headers["Authorization"] = f"Bearer {SUMMARY_LLM_API_KEY}"

        try:
            # Retry configuration
            connect_retry_delays = [1, 2, 4, 8]

            for attempt, delay in enumerate(connect_retry_delays, 1):
                try:
                    # Make the API request using httpx
                    async with httpx.AsyncClient() as client:
                        response = await client.post(
                            SUMMARY_LLM_BASE_URL,
                            headers=headers,
                            json=payload,
                            timeout=httpx.Timeout(None, connect=30, read=300),
                        )
                        if response.text and len(response.text) >= 50:
                            tail_50 = response.text[-50:]
                            repeat_count = response.text.count(tail_50)
                            if repeat_count > 5:
                                print("Repeat detected in extract_info_with_llm", file=sys.stderr)
                                continue

                    # Check if the request was successful
                    if (
                        "Requested token count exceeds the model's maximum context length"
                        in response.text
                        or "longer than the model's context length" in response.text
                    ):
                        prompt = get_prompt_with_truncation(
                            info_to_extract,
                            content,
                            truncate_last_num_chars=40960 * attempt,
                        )  # remove 40k * num_attempts chars from the end of the content
                        payload["messages"][0]["content"] = prompt
                        continue  # no need to raise error here, just try again

                    response.raise_for_status()
                    break  # Success, exit retry loop

                except httpx.ConnectTimeout as e:
                    # connection timeout, retry
                    if attempt < len(connect_retry_delays):
                        delay = connect_retry_delays[attempt]
                        print(
                            f"Jina Scrape and Extract Info: Connection timeout, {delay}s before next attempt "
                            f"(attempt {attempt + 1})", file=sys.stderr
                        )
                        await asyncio.sleep(delay)
                        continue
                    print(
                        "Jina Scrape and Extract Info: Connection retry attempts exhausted", file=sys.stderr
                    )
                    raise e

                except httpx.ConnectError as e:
                    # connection error, retry
                    if attempt < len(connect_retry_delays):
                        delay = connect_retry_delays[attempt]
                        print(
                            f"Jina Scrape and Extract Info: Connection error: {e}, "
                            f"{delay}s before next attempt", file=sys.stderr
                        )
                        await asyncio.sleep(delay)
                        continue
                    print(
                        "Jina Scrape and Extract Info: Connection retry attempts exhausted", file=sys.stderr
                    )
                    raise e

                except httpx.ReadTimeout as e:
                    # read timeout, LLM API is too slow, no need to retry
                    if attempt < len(connect_retry_delays):
                        print(
                            f"Jina Scrape and Extract Info: LLM API attempt {attempt} read timeout", file=sys.stderr
                        )
                        continue
                    print(
                        f"Jina Scrape and Extract Info: LLM API read timeout retry attempts exhausted, "
                        f"please check the request complexity, information to extract: {info_to_extract}, "
                        f"length of content: {len(content)}, url: {url}", file=sys.stderr
                    )
                    raise e

                except httpx.HTTPStatusError as e:
                    print(
                        f"Jina Scrape and Extract Info: HTTP error for LLM API: {e}, response.text: {response.text}",
                        file=sys.stderr
                    )
                    raise httpx.HTTPStatusError(
                        f"response.text: {response.text}",
                        request=e.request,
                        response=e.response,
                    ) from e

                except httpx.RequestError as e:
                    print(
                        f"Jina Scrape and Extract Info: Unknown request exception: {e}", file=sys.stderr
                    )
                    raise e

        except Exception as e:
            error_msg = f"Jina Scrape and Extract Info: Unexpected error during LLM API call: {str(e)}"
            print(error_msg, file=sys.stderr)
            return {
                "success": False,
                "extracted_info": "",
                "error": error_msg,
                "model_used": model,
                "tokens_used": 0,
            }

        # Parse the response
        try:
            response_data = response.json()

        except json.JSONDecodeError as e:
            error_msg = (
                f"Jina Scrape and Extract Info: Failed to parse LLM API response: {str(e)}"
            )
            print(error_msg, file=sys.stderr)
            print(f"Raw response: {response.text}", file=sys.stderr)
            return {
                "success": False,
                "extracted_info": "",
                "error": error_msg,
                "model_used": model,
                "tokens_used": 0,
            }

        print(
            f"Jina Scrape and Extract Info: Info to extract: {info_to_extract}, "
            f"LLM Response data: {response_data}", file=sys.stderr
        )

        # Extract summary from response
        if "choices" in response_data and len(response_data["choices"]) > 0:
            try:
                summary = response_data["choices"][0]["message"]["content"]
            except Exception as e:
                error_msg = f"Jina Scrape and Extract Info: Failed to get summary from LLM API response: {str(e)}"
                print(error_msg, file=sys.stderr)
                return {
                    "success": False,
                    "extracted_info": "",
                    "error": error_msg,
                    "model_used": model,
                    "tokens_used": 0,
                }

            # Extract token usage if available
            tokens_used = 0
            if "usage" in response_data:
                tokens_used = response_data["usage"].get("total_tokens", 0)

            return {
                "success": True,
                "extracted_info": summary,
                "error": "",
                "model_used": model,
                "tokens_used": tokens_used,
            }
        if "candidates" in response_data and len(response_data["candidates"]) > 0:
            try:
                summary = response_data["candidates"][0]["content"]["parts"][0]["text"]
            except Exception as e:
                error_msg = f"Jina Scrape and Extract Info: Failed to get summary from LLM API response: {str(e)}"
                print(error_msg, file=sys.stderr)
                return {
                    "success": False,
                    "extracted_info": "",
                    "error": error_msg,
                    "model_used": model,
                    "tokens_used": 0,
                }

            return {
                "success": True,
                "extracted_info": summary,
                "error": "",
                "model_used": model,
                "tokens_used": 0,
            }
        if "error" in response_data:
            error_msg = (
                f"Jina Scrape and Extract Info: LLM API error: {response_data['error']}"
            )
            print(error_msg, file=sys.stderr)
            return {
                "success": False,
                "extracted_info": "",
                "error": error_msg,
                "model_used": model,
                "tokens_used": 0,
            }
        error_msg = (
            f"Jina Scrape and Extract Info: No valid response from LLM API, "
            f"response data: {response_data}"
        )
        print(error_msg, file=sys.stderr)
        return {
            "success": False,
            "extracted_info": "",
            "error": error_msg,
            "model_used": model,
            "tokens_used": 0,
        }

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
    """
    print(f"Starting the MCP server on port {port} with transport {transport}", file=sys.stderr)
    assert transport.lower() in ["stdio", "sse"], "Transport should be stdio or sse"
    logger = get_logger("Service:jina_scrape_llm_summary")
    logger.info("Starting the MCP server")
    mcp = build_server(int(port))
    mcp.run(transport=transport.lower())
