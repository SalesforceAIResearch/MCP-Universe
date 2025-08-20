"""
Utility functions for agent-related operations.

This module provides functions for handling tool descriptions,
building system prompts, and rendering prompt templates.
"""
from typing import List, Dict, Optional

import yaml
from jinja2 import Environment
from mcp.types import Tool


def get_tools_description(tools: Dict[str, List[Tool]]) -> str:
    """
    Generate a formatted description of the specified tools.

    This function creates a detailed description of each tool, including
    the server name, tool name, description, and arguments.

    Args:
        tools (Dict[str, List[Tool]]): A dictionary of tools, where keys are
            server names and values are lists of Tool objects.

    Returns:
        str: A formatted string containing descriptions of all tools.
    """
    descriptions = []
    for server_name, tool_list in tools.items():
        for tool in tool_list:
            args = []
            if "properties" in tool.inputSchema:
                for param_name, param_info in tool.inputSchema["properties"].items():
                    info = "\n".join(["    " + line for line in
                                      yaml.dump(param_info, sort_keys=False, indent=2).split("\n")])
                    arg = f"- {param_name}:\n{info}".strip()
                    if param_name in tool.inputSchema.get("required", []):
                        arg += "\n    required: true"
                    args.append(arg.strip())
            lines = [line for line in tool.description.split("\n") if line.strip()]
            arguments = f"\n{chr(10).join(args)}" if args else " No arguments"
            description = (f"Server: {server_name}\n"
                           f"Tool: {tool.name}\n"
                           f"Description:\n{chr(10).join(lines)}\n"
                           f"Arguments:{arguments}")
            descriptions.append(description)
    return "\n\n".join(descriptions).strip()


def build_system_prompt(
        system_prompt_template: str,
        tool_prompt_template: str = "",
        tools: Optional[Dict[str, List[Tool]]] = None,
        include_tool_description: Optional[bool] = True,
        **kwargs
) -> str:
    """
    Build an agent system prompt using provided templates and tools.

    This function combines system and tool prompt templates with tool descriptions
    to create a comprehensive system prompt for an agent.

    Args:
        system_prompt_template (str): The template for the system prompt. If it
            ends with ".j2", it's treated as a path to a Jinja2 template file.
        tool_prompt_template (str, optional): The template for the tool prompt. If it
            ends with ".j2", it's treated as a path to a Jinja2 template file.
        tools (Dict[str, List[Tool]], optional): A dictionary of tools, where keys
            are server names and values are lists of Tool objects.
        include_tool_description (bool, optional): Whether to include tool descriptions
            in the prompt if tools exist.
        **kwargs: Additional keyword arguments to be passed to the template rendering.

    Returns:
        str: The rendered system prompt.

    Note:
        If both tool_prompt_template and tools are provided, a tools prompt will be
        generated and included in the final system prompt.
    """
    if system_prompt_template.endswith(".j2"):
        with open(system_prompt_template, "r", encoding="utf-8") as f:
            system_prompt_template = f.read()
    if tool_prompt_template.endswith(".j2"):
        with open(tool_prompt_template, "r", encoding="utf-8") as f:
            tool_prompt_template = f.read()

    tools_prompt = ""
    tools_description = get_tools_description(tools) if tools else ""
    if include_tool_description and tool_prompt_template and tools_description:
        env = Environment(trim_blocks=True, lstrip_blocks=True)
        template = env.from_string(tool_prompt_template)
        kwargs.update({"TOOLS_DESCRIPTION": tools_description})
        tools_prompt = template.render(**kwargs)

    env = Environment(trim_blocks=True, lstrip_blocks=True)
    template = env.from_string(system_prompt_template)
    if tools_prompt:
        kwargs.update({"TOOLS_PROMPT": tools_prompt})
    return template.render(**kwargs).strip()


def render_prompt_template(prompt_template: str, **kwargs):
    """
    Render a prompt using a given template and variables.

    This function takes a prompt template (either as a string or a file path)
    and renders it using the provided variables.

    Args:
        prompt_template (str): The prompt template string or path to a .j2 template file.
        **kwargs: Variables to be used in template rendering.

    Returns:
        str: The rendered prompt.

    Note:
        If prompt_template ends with ".j2", it's treated as a path to a Jinja2 template file.
    """
    if prompt_template.endswith(".j2"):
        with open(prompt_template, "r", encoding="utf-8") as f:
            prompt_template = f.read()
    env = Environment(trim_blocks=True, lstrip_blocks=True)
    template = env.from_string(prompt_template)
    return template.render(**kwargs).strip()
