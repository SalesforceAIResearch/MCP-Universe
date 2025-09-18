"""
Utility functions for agent-related operations.

This module provides functions for handling tool descriptions,
building system prompts, and rendering prompt templates.
"""
import json
from typing import Any, Dict, Iterable, List, Optional, Union, Tuple
import re
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


def _sanitize_ident(name: str) -> str:
    """Relaxed Harmony-style identifier: keep letters/digits/_/-; replace others with '_'."""
    out = []
    for ch in name:
        if ch.isalnum() or ch in ("_", "-"):
            out.append(ch)
        else:
            out.append("_")
    s = "".join(out)
    return s or "_"  # avoid empty

_TS_IDENT_RE = re.compile(r'^[A-Za-z_]\w*$')

def _format_ts_prop_key(key: str) -> str:
    """
    Keep hyphens for object property keys by quoting when not a bare identifier.
    """
    if _TS_IDENT_RE.match(key):
        return key
    return json.dumps(key, ensure_ascii=False)  # e.g. "API-post-page"

def _jsonschema_to_ts(schema: Optional[Dict[str, Any]]) -> str:
    """Tiny JSON-Schema → TS-ish mapper for Harmony tool arg blocks."""
    if not schema:
        return "any"

    def to_ts(s: Any) -> str:
        if s is None:
            return "any"
        if isinstance(s, bool):
            return "any" if s else "never"
        if not isinstance(s, dict):
            return "any"

        t = s.get("type")
        if isinstance(t, list):
            return " | ".join(to_ts({"type": x}) for x in t)

        if "enum" in s and isinstance(s["enum"], list):
            vals = s["enum"]
            if all(isinstance(v, str) for v in vals):
                return " | ".join(json.dumps(v, ensure_ascii=False) for v in vals)

        if t == "string":
            return "string"
        if t in ("number", "integer"):
            return "number"
        if t == "boolean":
            return "boolean"
        if t == "array":
            items = s.get("items") or {}
            return f"{to_ts(items)}[]"

        if t == "object" or "properties" in s or "additionalProperties" in s:
            props = s.get("properties") or {}
            required = set(s.get("required") or [])
            lines: List[str] = []
            for k, v in props.items():
                k_id = _format_ts_prop_key(k)  # <— preserve hyphens by quoting if needed
                opt = "" if k in required else "?"
                desc = v.get("description")
                if isinstance(desc, str) and desc.strip():
                    lines.append(f"// {desc.strip()}")
                lines.append(f"{k_id}{opt}: {to_ts(v)},")
            if "additionalProperties" in s:
                ap = s["additionalProperties"]
                if ap not in (False, None):
                    ap_ts = to_ts(ap)
                    lines.append(f"[key: string]: {ap_ts},")
            return "{\n" + ("\n".join(lines)) + "\n}"

        for key in ("oneOf", "anyOf"):
            if isinstance(s.get(key), list) and s[key]:
                return " | ".join(to_ts(sub) for sub in s[key])

        if isinstance(s.get("allOf"), list) and s["allOf"]:
            return " & ".join(to_ts(sub) for sub in s["allOf"])

        return "any"

    return to_ts(schema)


def render_tools_namespace(
    tools_by_server: Dict[str, Iterable[Any]],
    *,
    title: str = "functions",
) -> str:
    """
    Render a Harmony 'namespace functions { ... }' that aggregates tools from multiple MCP servers.
    - Each tool is emitted as:  type {server}__{tool} = (_: <TS>) => any;
    - Tool objects may be dicts (OpenAI-style) or objects with attributes: name, description, inputSchema.
    - JSON-Schema is taken from: tool['function']['parameters'] OR tool.inputSchema
    """
    lines: List[str] = ["# Tools", f"## {title}", "", f"namespace {title} {{", ""]

    def extract_one(tool_obj: Any) -> Optional[Dict[str, Any]]:
        if isinstance(tool_obj, dict) and tool_obj.get("type") == "function":
            f = tool_obj.get("function") or {}
            return {
                "name": f.get("name"),
                "description": f.get("description"),
                "schema": f.get("parameters"),
            }
        name = getattr(tool_obj, "name", None)
        if name:
            return {
                "name": name,
                "description": getattr(tool_obj, "description", None),
                "schema": getattr(tool_obj, "inputSchema", None),
            }
        return None

    for server in sorted(tools_by_server.keys()):
        tools = list(tools_by_server[server] or [])
        if not tools:
            continue
        lines.append(f"// --- server: {server} ---")
        for t in tools:
            meta = extract_one(t)
            if not meta or not meta.get("name"):
                continue
            tool_name = meta["name"]
            # Hyphens are preserved here
            fq_name = f"{_sanitize_ident(server)}__{_sanitize_ident(tool_name)}"
            desc = (meta.get("description") or "").strip()
            if desc:
                lines.append(f"// {desc}")
            else:
                lines.append(f"// Tool from '{server}': {tool_name}")
            ts_args = _jsonschema_to_ts(meta.get("schema"))
            lines.append(f"type {fq_name} = (_: {ts_args}) => any;")
            lines.append("")
        lines.append("")

    lines.append(f"}} // namespace {title}")
    return "\n".join(lines)


def render_harmony_chain(
    developer_instructions: str,
    user_first_message: str,
    # Each round MUST have analysis; tool_call/tool_result are optional
    rounds: List[Dict[str, Any]],    
    system_identity: str = "You are ChatGPT, a large language model trained by OpenAI.",
    knowledge_cutoff: str = "2024-06",
    reasoning: str = "high",
    tools_namespace_ts: Optional[str] = "",   # string from render_tools_namespace(...)
) -> str:
    """
    Format a multi-round tool-calling transcript in Harmony
    
    Parameters:
    - developer_instructions: your instructions for the assistant/developer message.
    - tools_namespace_ts: TypeScript namespace block defining tools.
    - user_first_message: the user’s initial input.
    - rounds: a list of steps; each includes at least:
         {
           "analysis": str,        # required
           "tool_call": {"name": str, "arguments": Any},  # optional
           "tool_result": Any                # optional
         }
    """
    parts: List[str] = []

    # --- system message
    sys_lines = [
        "<|start|>system<|message|>" + system_identity,
        f"Knowledge cutoff: {knowledge_cutoff}",
        "",
        f"Reasoning: {reasoning}",
        "",
        "# Valid channels: analysis, commentary, final. Channel must be included for every message."
    ]
    if tools_namespace_ts:
        sys_lines.append("Calls to these tools must go to the commentary channel: 'functions'.")
    sys_lines.append("<|end|>")
    parts.append("\n".join(sys_lines) + "\n")

    # --- developer + tools
    dev = ["\n<|start|>developer<|message|># Instructions\n", developer_instructions.strip(), ""]
    if tools_namespace_ts:
        dev += [tools_namespace_ts, ""]
    dev.append("<|end|>")
    parts.append("\n".join(dev))

    # --- user message
    parts.append(f"<|start|>user<|message|>{user_first_message}<|end|>")

    # --- rounds of tool calls with required analysis
    for idx, step in enumerate(rounds):
        # enforce required fields
        if "analysis" not in step or not isinstance(step["analysis"], str) or not step["analysis"].strip():
            raise ValueError(f"Round {idx} missing non-empty 'analysis'.")

        # 1. Assistant analysis
        parts.append("<|start|>assistant<|channel|>analysis<|message|>")
        parts.append(step["analysis"].strip())
        parts.append("<|end|>\n")

        # 2. Optional Tool call (assistant commentary)
        tool_call = step.get("tool_call") if isinstance(step.get("tool_call"), dict) else None
        name = tool_call.get("name") if tool_call else None
        if name:
            args = tool_call.get("arguments", {})
            parts.append(
                f"<|start|>assistant<|channel|>commentary to=functions.{name} "
                f"<|constrain|>json<|message|>{json.dumps(args, ensure_ascii=False)}<|call|>\n"
            )

            # 3. Optional Tool result (tool → assistant commentary)
            if "tool_result" in step and step["tool_result"] is not None:
                parts.append(
                    f"<|start|>functions.{name} to=assistant<|channel|>commentary<|message|>{step["tool_result"]}<|end|>\n"
                )
    parts.append("<|start|>assistant<|channel|>analysis<|message|>")
    # Join everything
    return "".join(parts)



# ---------- Regex ----------
COMMENTARY_HEADER_RE = re.compile(
    r"<\|start\|>\s*assistant.*?<\|channel\|>\s*commentary\b.*?<\|message\|>",
    re.DOTALL,
)
TO_NAME_RE = re.compile(r"\bto=functions\.([^\s<{]+)")
# Stop at any structural tag that can follow args, including optional <|call|>
NEXT_TAG_RE = re.compile(r"(<\|start\|>|<\|end\|>|<\|call\|>)", re.DOTALL)

# Compact form, e.g.:
# assistantcommentary to=functions.server__tool json{...}
# assistantcommentary   to=functions.tool   { ... }
COMPACT_COMMENTARY_RE = re.compile(
    r"\bassistantcommentary\b(?P<after>.*?)(?=(\bassistantcommentary\b|<\|start\|>|<\|end\|>|\Z))",
    re.DOTALL,
)

# ---------- Balanced JSON scanner ----------
def _scan_balanced_json(s: str, start_idx: int) -> Optional[Dict[str, Any]]:
    if start_idx >= len(s) or s[start_idx] != "{":
        return None
    depth, in_str, esc = 0, False, False
    j = start_idx
    while j < len(s):
        ch = s[j]
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
        else:
            if ch == '"':
                in_str = True
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    raw = s[start_idx : j + 1]
                    try:
                        val = json.loads(raw)
                    except Exception:
                        val = raw
                    return {"raw": raw, "end": j + 1, "value": val}
        j += 1
    return None

# ---------- Helpers ----------
def _split_server_tool(tool_name: Optional[str]) -> Tuple[str, str]:
    if not tool_name:
        return "", ""
    for sep in ("__", ".", "_"):
        if sep in tool_name:
            a, b = tool_name.split(sep, 1)
            return a, b
    return "", tool_name

def _slice_until_next_tag(text: str, start: int) -> Tuple[str, int]:
    m = NEXT_TAG_RE.search(text, start)
    if not m:
        return text[start:].strip(), len(text)
    return text[start:m.start()].strip(), m.start()

# ---------- Parsers ----------
# ---------- Regex ----------
COMMENTARY_HEADER_RE = re.compile(
    r"<\|start\|>\s*assistant.*?<\|channel\|>\s*commentary\b.*?<\|message\|>",
    re.DOTALL,
)
FINAL_HEADER_RE = re.compile(
    r"<\|start\|>\s*assistant.*?<\|channel\|>\s*final\b.*?<\|message\|>",
    re.DOTALL,
)
TO_NAME_RE = re.compile(r"\bto=functions\.([^\s<{]+)")
# Stop at any structural tag that can follow args, including optional <|call|>
NEXT_TAG_RE = re.compile(r"(<\|start\|>|<\|end\|>|<\|call\|>)", re.DOTALL)

# Compact form, e.g.:
# assistantcommentary to=functions.server__tool json{...}
# assistantcommentary   to=functions.tool   { ... }
COMPACT_COMMENTARY_RE = re.compile(
    r"\bassistantcommentary\b(?P<after>.*?)(?=(\bassistantcommentary\b|\bassistantfinal\b|<\|start\|>|<\|end\|>|\Z))",
    re.DOTALL,
)
# Compact final form, e.g.:
# assistantfinal {...}
# assistantfinal [ ... ]
# assistantfinal plain text...
COMPACT_FINAL_RE = re.compile(
    r"\bassistantfinal\b(?P<after>.*?)(?=(\bassistantcommentary\b|\bassistantfinal\b|<\|start\|>|<\|end\|>|\Z))",
    re.DOTALL,
)

# ---------- Balanced JSON/Array scanner ----------
def _scan_balanced_json_like(s: str, start_idx: int) -> Optional[Dict[str, Any]]:
    """
    Scan starting at either '{' or '[' and return a parsed JSON value (or raw text) plus end index.
    Supports strings/escapes and nested braces/brackets.
    """
    if start_idx >= len(s) or s[start_idx] not in "{[":
        return None

    opening = s[start_idx]
    closing = "}" if opening == "{" else "]"

    depth, in_str, esc = 0, False, False
    j = start_idx
    while j < len(s):
        ch = s[j]
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
        else:
            if ch == '"':
                in_str = True
            elif ch == opening:
                depth += 1
            elif ch == closing:
                depth -= 1
                if depth == 0:
                    raw = s[start_idx : j + 1]
                    try:
                        val = json.loads(raw)
                    except Exception:
                        val = raw
                    return {"raw": raw, "end": j + 1, "value": val}
        j += 1
    return None

# Backward-compat: keep the old name for code that imports it elsewhere.
def _scan_balanced_json(s: str, start_idx: int) -> Optional[Dict[str, Any]]:
    return _scan_balanced_json_like(s, start_idx)

# ---------- Helpers ----------
def _split_server_tool(tool_name: Optional[str]) -> Tuple[str, str]:
    if not tool_name:
        return "", ""
    for sep in ("__", ".", "_"):
        if sep in tool_name:
            a, b = tool_name.split(sep, 1)
            return a, b
    return "", tool_name

def _slice_until_next_tag(text: str, start: int) -> Tuple[str, int]:
    m = NEXT_TAG_RE.search(text, start)
    if not m:
        return text[start:].strip(), len(text)
    return text[start:m.start()].strip(), m.start()

# ---------- Parsers ----------
def parse_analysis(text: str) -> str:
    """
    Return the analysis as a single string.

    Analysis is the plain text at the top, before the first structural marker.
    We stop at the earliest of: <|start|>, 'assistantcommentary', or <|end|>.
    If no analysis text is found, return an empty string.
    """
    idx_start = text.find("<|start|>")
    m_compact = re.search(r"\bassistantcommentary\b", text)
    idx_compact = m_compact.start() if m_compact else -1
    idx_end = text.find("<|end|>")

    candidates = [i for i in (idx_start, idx_compact, idx_end) if i != -1]
    cutoff = min(candidates) if candidates else -1

    prefix = text if cutoff == -1 else text[:cutoff]
    prefix = prefix.strip()
    return prefix

def _parse_tool_call_harmony(text: str) -> List[Dict[str, Any]]:
    calls: List[Dict[str, Any]] = []
    for m in COMMENTARY_HEADER_RE.finditer(text):
        header = m.group(0)  # includes <|message|>
        name_m = TO_NAME_RE.search(header)
        tool_name = name_m.group(1) if name_m else None
        server, tool = _split_server_tool(tool_name)

        i, n = m.end(), len(text)
        while i < n and text[i].isspace():
            i += 1

        if i < n and text[i] in "{[":
            parsed = _scan_balanced_json_like(text, i)
            if parsed:
                args_val = parsed["value"]
            else:
                slice_text, _ = _slice_until_next_tag(text, i)
                args_val = slice_text
        else:
            slice_text, _ = _slice_until_next_tag(text, i)
            args_val = slice_text

        calls.append({"tool_name": tool_name, "server": server, "tool": tool, "arguments": args_val})
    return calls

def _parse_tool_call_compact(text: str) -> List[Dict[str, Any]]:
    """
    Parse blocks that start with 'assistantcommentary' and include 'to=functions.NAME'
    followed by optional 'json' token and a JSON object/array. If none found, args="".
    """
    calls: List[Dict[str, Any]] = []
    for m in COMPACT_COMMENTARY_RE.finditer(text):
        block = m.group(0)
        name_m = TO_NAME_RE.search(block)
        tool_name = name_m.group(1) if name_m else None
        server, tool = _split_server_tool(tool_name)

        start_search_pos = name_m.end() if name_m else 0
        # Find first '{' or '[' after the tool name
        brace_idx = len(block)
        for ch in "{[":
            idx = block.find(ch, start_search_pos)
            if idx != -1:
                brace_idx = min(brace_idx, idx)
        args_val: Any = ""
        if brace_idx != len(block):
            parsed = _scan_balanced_json_like(block, brace_idx)
            if parsed:
                args_val = parsed["value"]
            else:
                args_val = block[brace_idx:].strip()

        calls.append({"tool_name": tool_name, "server": server, "tool": tool, "arguments": args_val})
    return calls

def parse_tool_call(text: str) -> List[Dict[str, Any]]:
    # Merge both styles; Harmony first, then compact.
    calls = _parse_tool_call_harmony(text)
    calls.extend(_parse_tool_call_compact(text))
    # Normalize: ensure arguments is always a dict
    for c in calls:
        args_val = c.get("arguments")
        if not isinstance(args_val, dict):
            c["arguments"] = {"value": args_val}
    return calls

# ---------- Final answer parsers (JSON-only) ----------
def _final_json_after_idx(text: str, i: int) -> Optional[Any]:
    """Return a parsed JSON value starting at i if it begins with '{' or '['; else None."""
    n = len(text)
    while i < n and text[i].isspace():
        i += 1
    if i < n and text[i] in "{[":
        parsed = _scan_balanced_json_like(text, i)
        if parsed:
            return parsed["value"]
    return None

def _parse_final_harmony_json(text: str) -> Optional[Any]:
    m = FINAL_HEADER_RE.search(text)
    if not m:
        return None
    return _final_json_after_idx(text, m.end())

def _parse_final_compact_json(text: str) -> Optional[Any]:
    m = COMPACT_FINAL_RE.search(text)
    if not m:
        return None
    block = m.group(0)
    after = m.group("after") or ""
    block_start = text.find(block)
    after_start = block_start + (block.find(after) if after else len(block))
    return _final_json_after_idx(text, after_start)

def parse_final(text: str) -> Optional[Any]:
    """
    Returns the JSON value from the final answer:
      - dict/list when the payload is valid JSON or JSON array
      - None if no JSON final is found
    """
    return _parse_final_harmony_json(text) or _parse_final_compact_json(text)

def parse_harmony(text: str) -> Dict[str, Any]:
    return {
        "analysis": parse_analysis(text),  # always a string (may be empty)
        "tool_call": parse_tool_call(text),
        "final": parse_final(text),  # dict/list or None
    }