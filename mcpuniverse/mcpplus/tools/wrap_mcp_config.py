"""CLI tool to wrap existing MCP servers from an mcp.json config file.

Usage:
    mcp-build-plus --mcp-config ~/.cursor/mcp.json

This will:
- Read your existing mcp.json
- For each server, create a wrapped proxy config
- Add <server>-plus entries to your mcp.json
- Store proxy configs in ~/.mcpplus/configs/

Requires OPENAI_API_KEY environment variable to be set.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


def _load_json(path: Path) -> Dict[str, Any]:
    """Load JSON file, return empty dict if doesn't exist."""
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def _write_json(path: Path, data: Dict[str, Any]) -> None:
    """Write JSON file with pretty formatting."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
        f.write("\n")


def _get_config_dir() -> Path:
    """Get the mcpplus config directory."""
    return Path.home() / ".mcpplus" / "configs"


def _build_proxy_config(
    upstream: str,
    server_name: str,
    command: str,
    args: List[str],
    env: Optional[Dict[str, str]] = None,
    llm_model: str = "gpt-4.1",
    llm_api_key_env: str = "OPENAI_API_KEY",
    token_threshold: int = 500,
) -> Dict[str, Any]:
    """Build a proxy wrapper config for the given upstream server."""
    return {
        "upstream_server": upstream,
        "server_name": server_name,
        "transport": "stdio",
        "upstream_address": "",
        "timeout": 30,
        "upstream_command": command,
        "upstream_args": args,
        "upstream_env": env or {},
        "llm": {
            "name": "openai",
            "config": {
                "model_name": llm_model,
                "api_key": f"${llm_api_key_env}",
            },
        },
        "wrapper": {
            "enabled": True,
            "token_threshold": token_threshold,
            "use_agent_llm": False,
            "post_process_llm": None,
            "enable_memory": True,
            "execution_timeout": 500,
            "max_iterations": 3,
            "enable_reflection": False,
            "max_tool_output_chars": None,
        },
    }


def _build_cursor_entry(
    server_name: str,  # pylint: disable=unused-argument
    config_path: Path,
    llm_api_key_env: str = "OPENAI_API_KEY",
    llm_api_key_value: Optional[str] = None,
) -> Dict[str, Any]:
    """Build an MCP server entry for Cursor/Claude config."""
    # Use actual key value if provided, otherwise fall back to env var reference
    env_value = llm_api_key_value if llm_api_key_value else f"${llm_api_key_env}"
    return {
        "command": "python3",
        "args": [
            "-m",
            "mcpuniverse.mcpplus.mcp.proxy_server",
            "--config",
            str(config_path),
            "--transport",
            "stdio",
        ],
        "env": {
            llm_api_key_env: env_value,
        },
    }


def _parse_mcp_config(config_path: Path) -> Dict[str, Dict[str, Any]]:
    """Parse an mcp.json file and extract server definitions."""
    data = _load_json(config_path)

    # Handle both flat format and nested mcpServers format
    if "mcpServers" in data:
        return data.get("mcpServers", {})

    # Assume flat format where keys are server names
    return {k: v for k, v in data.items() if isinstance(v, dict) and "command" in v}


def _prompt_confirmation(message: str = "Proceed?") -> bool:
    """Prompt user for yes/no confirmation."""
    while True:
        response = input(f"\n{message} [y/N]: ").strip().lower()
        if response in ("y", "yes"):
            return True
        if response in ("n", "no", ""):
            return False
        print("Please enter 'y' or 'n'")


def _prepare_wrap_changes(
    mcp_config_path: Path,
    servers: Optional[List[str]] = None,
    llm_model: str = "gpt-4.1",
    llm_api_key_env: str = "OPENAI_API_KEY",
    token_threshold: int = 500,
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Tuple[Path, Dict[str, Any]]], Optional[str]]:
    """
    Prepare the changes that will be made (without writing anything).

    Returns:
        Tuple of (full_config, new_mcp_entries, proxy_configs, api_key_value)
        - full_config: The full mcp.json config with new entries added
        - new_mcp_entries: Just the new server entries to be added
        - proxy_configs: Dict of {server_name: (config_path, config_data)}
        - api_key_value: The API key value from environment (or None)
    """
    config_dir = _get_config_dir()
    existing_servers = _parse_mcp_config(mcp_config_path)

    # Read actual API key from environment
    api_key_value = os.environ.get(llm_api_key_env)

    if not existing_servers:
        print(f"No MCP servers found in {mcp_config_path}", file=sys.stderr)
        sys.exit(1)

    # Filter to requested servers
    if servers:
        missing = set(servers) - set(existing_servers.keys())
        if missing:
            print(f"Servers not found in config: {missing}", file=sys.stderr)
            sys.exit(1)
        servers_to_wrap = {k: v for k, v in existing_servers.items() if k in servers}
    else:
        # Skip servers that are already -plus versions
        servers_to_wrap = {k: v for k, v in existing_servers.items() if not k.endswith("-plus")}

    if not servers_to_wrap:
        print("No servers to wrap (all may already be wrapped)", file=sys.stderr)
        sys.exit(0)

    # Load full config to preserve structure
    full_config = _load_json(mcp_config_path)
    if "mcpServers" in full_config:
        servers_section = full_config["mcpServers"]
    else:
        servers_section = full_config

    new_entries = {}
    proxy_configs = {}

    for name, server_cfg in servers_to_wrap.items():
        plus_name = f"{name}-plus"

        # Extract command/args from server config
        command = server_cfg.get("command", "")
        args = server_cfg.get("args", [])
        env = server_cfg.get("env", {})

        if not command:
            continue

        # Build proxy config
        proxy_config = _build_proxy_config(
            upstream=name,
            server_name=plus_name,
            command=command,
            args=args,
            env=env,
            llm_model=llm_model,
            llm_api_key_env=llm_api_key_env,
            token_threshold=token_threshold,
        )

        proxy_config_path = config_dir / f"proxy_{name}.json"
        proxy_configs[plus_name] = (proxy_config_path, proxy_config)

        # Build cursor entry
        cursor_entry = _build_cursor_entry(
            server_name=plus_name,
            config_path=proxy_config_path,
            llm_api_key_env=llm_api_key_env,
            llm_api_key_value=api_key_value,
        )
        new_entries[plus_name] = cursor_entry

    # Add new entries to config (in memory only)
    servers_section.update(new_entries)

    return full_config, new_entries, proxy_configs, api_key_value


def wrap_servers(
    mcp_config_path: Path,
    servers: Optional[List[str]] = None,
    llm_model: str = "gpt-4.1",
    llm_api_key_env: str = "OPENAI_API_KEY",
    token_threshold: int = 500,
    dry_run: bool = False,
    yes: bool = False,
    output_path: Optional[Path] = None,
) -> Dict[str, Any]:
    """
    Wrap MCP servers from a config file.

    Args:
        mcp_config_path: Path to the mcp.json file
        servers: List of server names to wrap (None = all)
        llm_model: LLM model to use for post-processing
        llm_api_key_env: Environment variable name for API key
        token_threshold: Min tokens to trigger post-processing
        dry_run: If True, don't write files, just print what would be done
        yes: If True, skip confirmation prompt
        output_path: Path to write the updated config (default: same as input)

    Returns:
        The updated config dict
    """
    # Prepare all changes first (no writes yet)
    full_config, new_entries, proxy_configs, api_key_value = _prepare_wrap_changes(
        mcp_config_path=mcp_config_path,
        servers=servers,
        llm_model=llm_model,
        llm_api_key_env=llm_api_key_env,
        token_threshold=token_threshold,
    )

    if not new_entries:
        print("No servers to wrap.", file=sys.stderr)
        sys.exit(0)

    output = output_path or mcp_config_path

    # Show the user what will happen
    print("=" * 60)
    print("MCP+ Wrapper Configuration Preview")
    print("=" * 60)

    # API key status
    if api_key_value:
        print(f"\n[API Key] Found {llm_api_key_env} in environment.")
        print("          Will embed in config (keep mcp.json secure).")
    else:
        print(f"\n[API Key] Warning: {llm_api_key_env} not found in environment.")
        print(f"          Will use ${llm_api_key_env} reference.")

    # Show proxy configs that will be created
    print(f"\n[Proxy Configs] Will create {len(proxy_configs)} file(s) in ~/.mcpplus/configs/:")
    for _, (config_path, _) in proxy_configs.items():
        print(f"  - {config_path}")

    # Show entries that will be added to mcp.json
    print(f"\n[MCP Config] Will add {len(new_entries)} server(s) to {output}:")
    print("-" * 60)
    print(json.dumps(new_entries, indent=2))
    print("-" * 60)

    # Explain what each -plus server does
    print("\n[What This Does]")
    print("  Each '-plus' server wraps the original server with intelligent")
    print("  output filtering. Long tool outputs are processed by an LLM to")
    print("  extract only the information relevant to your query.")
    print(f"\n  LLM Model: {llm_model}")
    print(f"  Token Threshold: {token_threshold} (outputs shorter than this pass through)")

    if dry_run:
        print("\n[Dry Run] No changes were made.")
        return full_config

    # Ask for confirmation (unless --yes flag)
    if not yes:
        if not _prompt_confirmation("Apply these changes?"):
            print("\nAborted. No changes were made.")
            sys.exit(0)

    # Write the changes
    print("\nApplying changes...")

    # Write proxy configs
    for _, (config_path, proxy_config) in proxy_configs.items():
        _write_json(config_path, proxy_config)
        print(f"  Created: {config_path}")

    # Write updated mcp.json
    _write_json(output, full_config)
    print(f"  Updated: {output}")

    print(f"\nSuccess! Added {len(new_entries)} wrapped server(s).")
    print("\nNext steps:")
    print("  1. Restart your MCP client (Cursor, Claude Desktop, etc.)")
    print("  2. Use the '-plus' servers (e.g., 'finance-plus' instead of 'finance')")

    return full_config


def parse_args() -> argparse.Namespace:
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="Wrap existing MCP servers with MCP+ intelligent output filtering.",
        epilog="Example: mcp-build-plus --mcp-config ~/.cursor/mcp.json",
    )
    parser.add_argument(
        "--mcp-config",
        required=True,
        help="Path to your mcp.json config file (e.g., ~/.cursor/mcp.json)",
    )
    parser.add_argument(
        "--servers",
        nargs="+",
        help="Specific server names to wrap (default: all)",
    )
    parser.add_argument(
        "--llm-model",
        default="gpt-4.1",
        help="LLM model for post-processing (default: gpt-4.1)",
    )
    parser.add_argument(
        "--llm-api-key-env",
        default="OPENAI_API_KEY",
        help="Env var name for LLM API key (default: OPENAI_API_KEY)",
    )
    parser.add_argument(
        "--token-threshold",
        type=int,
        default=500,
        help="Min tokens to trigger post-processing (default: 500)",
    )
    parser.add_argument(
        "--output",
        help="Path to write updated config (default: overwrite input)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be done without making changes",
    )
    parser.add_argument(
        "-y", "--yes",
        action="store_true",
        help="Skip confirmation prompt (use with caution)",
    )
    return parser.parse_args()


def main() -> None:
    """Entry point for mcp-build-plus command."""
    args = parse_args()

    mcp_config_path = Path(args.mcp_config).expanduser().resolve()
    if not mcp_config_path.exists():
        print(f"Config file not found: {mcp_config_path}", file=sys.stderr)
        sys.exit(1)

    output_path = Path(args.output).expanduser().resolve() if args.output else None

    wrap_servers(
        mcp_config_path=mcp_config_path,
        servers=args.servers,
        llm_model=args.llm_model,
        llm_api_key_env=args.llm_api_key_env,
        token_threshold=args.token_threshold,
        dry_run=args.dry_run,
        yes=args.yes,
        output_path=output_path,
    )


if __name__ == "__main__":
    main()
