"""CLI tool to wrap existing MCP servers from an mcp.json config file.

Usage:
    mcp-build-plus --mcp-config ~/.cursor/mcp.json

This will:
- Read your existing mcp.json
- For each server, create a wrapped proxy config
- Add <server>-plus entries to your mcp.json
- Store proxy configs in ~/.mcpplus/configs/

Requires an LLM API key environment variable to be set (default: OPENAI_API_KEY).
Supports multiple LLM providers: openai, gemini, anthropic, etc.
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


def _get_gateway_llm_config_fields(llm_provider: str) -> Dict[str, str]:
    """
    Get additional config fields needed for gateway LLM providers.

    Returns env var references (e.g., "$ENG_AI_MODEL_GW_URL") which will be
    expanded by the proxy server at runtime.

    Args:
        llm_provider: The LLM provider name

    Returns:
        Dict of additional config fields with $VAR references
    """
    extra_config = {}

    # Salesforce LLM Express Gateway
    if llm_provider == "sf_llm_express_gateway":
        extra_config["base_url"] = "$ENG_AI_MODEL_GW_URL"

    # Salesforce Research Gateway
    elif llm_provider == "sf_research_gateway":
        extra_config["base_url"] = "$RESEARCH_GATEWAY_URL"

    elif llm_provider == "azure":
        extra_config["azure_endpoint"] = "$AZURE_API_BASE"
        extra_config["api_version"] = "$AZURE_API_VERSION"

    return extra_config


def _build_proxy_config(
    upstream: str,
    server_name: str,
    command: Optional[str],
    args: Optional[List[str]],
    env: Optional[Dict[str, str]] = None,
    llm_provider: str = "openai",
    llm_model: str = "gpt-5-mini-2025-08-07",
    llm_api_key_env: str = "OPENAI_API_KEY",
    token_threshold: int = 2000,
    transport: str = "stdio",
    upstream_url: Optional[str] = None,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """Build a proxy wrapper config for the given upstream server."""
    # Build base LLM config
    llm_config = {
        "model_name": llm_model,
        "api_key": f"${llm_api_key_env}",
    }

    # Add gateway-specific config fields (e.g., base_url)
    gateway_config = _get_gateway_llm_config_fields(llm_provider)
    llm_config.update(gateway_config)

    config = {
        "upstream_server": upstream,
        "server_name": server_name,
        "transport": transport,
        "upstream_address": upstream_url or "",
        "timeout": 500,
        "upstream_command": command,
        "upstream_args": args if args is not None else [],
        "upstream_env": env or {},
        "llm": {
            "name": llm_provider,
            "config": llm_config,
        },
        "wrapper": {
            "enabled": True,
            "token_threshold": token_threshold,
            "post_process_llm": None,
            "llm_timeout": 500,
            "max_iterations": 3,
            "skip_iteration_on_size_failure": False,
        },
    }

    # Add headers if provided (for HTTP/SSE with auth)
    if headers:
        config["headers"] = headers

    return config


def _get_gateway_env_vars(llm_provider: str) -> Dict[str, str]:
    """
    Get required environment variables for gateway LLM providers.

    Args:
        llm_provider: The LLM provider name

    Returns:
        Dict of environment variable names and their values
    """
    env_vars = {}

    # Salesforce LLM Express Gateway
    if llm_provider == "sf_llm_express_gateway":
        if os.getenv("ENG_AI_MODEL_GW_URL"):
            env_vars["ENG_AI_MODEL_GW_URL"] = os.getenv("ENG_AI_MODEL_GW_URL")
        if os.getenv("ENG_AI_MODEL_GW_KEY"):
            env_vars["ENG_AI_MODEL_GW_KEY"] = os.getenv("ENG_AI_MODEL_GW_KEY")

    # Salesforce Research Gateway
    elif llm_provider == "sf_research_gateway":
        if os.getenv("RESEARCH_GATEWAY_URL"):
            env_vars["RESEARCH_GATEWAY_URL"] = os.getenv("RESEARCH_GATEWAY_URL")
        if os.getenv("SALESFORCE_GATEWAY_KEY"):
            env_vars["SALESFORCE_GATEWAY_KEY"] = os.getenv("SALESFORCE_GATEWAY_KEY")

    # Legacy Claude Gateway
    elif llm_provider == "claude_gateway":
        if os.getenv("SALESFORCE_GATEWAY_KEY"):
            env_vars["SALESFORCE_GATEWAY_KEY"] = os.getenv("SALESFORCE_GATEWAY_KEY")

    elif llm_provider == "azure":
        if os.getenv("AZURE_API_KEY"):
            env_vars["AZURE_API_KEY"] = os.getenv("AZURE_API_KEY")
        if os.getenv("AZURE_API_BASE"):
            env_vars["AZURE_API_BASE"] = os.getenv("AZURE_API_BASE")
        if os.getenv("AZURE_API_VERSION"):
            env_vars["AZURE_API_VERSION"] = os.getenv("AZURE_API_VERSION")

    return env_vars


def _build_mcp_entry(
    server_name: str,  # pylint: disable=unused-argument
    config_path: Path,
    llm_api_key_env: str = "OPENAI_API_KEY",
    llm_api_key_value: Optional[str] = None,
    llm_provider: str = "openai",
) -> Dict[str, Any]:
    """
    Build an MCP server entry for mcp.json config (Cursor, Claude Desktop, etc.).

    Uses sys.executable to get the absolute path to the current Python interpreter.
    This ensures Cursor/Claude Desktop can find the right Python with mcpuniverse installed,
    even if they don't load your shell environment.

    Args:
        server_name: Name of the server
        config_path: Path to the proxy config file
        llm_api_key_env: Environment variable name for the API key
        llm_api_key_value: Optional actual API key value
        llm_provider: The LLM provider being used

    Returns:
        MCP server configuration dict
    """
    # Use actual key value if provided, otherwise fall back to env var reference
    env_value = llm_api_key_value if llm_api_key_value else f"${llm_api_key_env}"

    # Build env vars dict
    env_dict = {llm_api_key_env: env_value}

    # Add gateway-specific environment variables
    gateway_env_vars = _get_gateway_env_vars(llm_provider)
    env_dict.update(gateway_env_vars)

    return {
        "command": sys.executable,  # Absolute path to current Python interpreter
        "args": [
            "-m",
            "mcpuniverse.extensions.mcpplus.tools.proxy_server",
            "--config",
            str(config_path),
            "--transport",
            "stdio",
        ],
        "env": env_dict,
    }


def _parse_mcp_config(config_path: Path) -> Dict[str, Dict[str, Any]]:
    """Parse an mcp.json file and extract server definitions."""
    data = _load_json(config_path)

    # Handle both flat format and nested mcpServers format
    if "mcpServers" in data:
        servers = data.get("mcpServers", {})
    else:
        # Assume flat format where keys are server names
        servers = data

    # Return servers that have either command (stdio), url (SSE), or http_url (HTTP)
    return {
        k: v for k, v in servers.items()
        if isinstance(v, dict) and ("command" in v or "url" in v or "http_url" in v)
    }


def _prompt_confirmation(message: str = "Proceed?") -> bool:
    """Prompt user for yes/no confirmation."""
    while True:
        response = input(f"\n{message} [y/N]: ").strip().lower()
        if response in ("y", "yes"):
            return True
        if response in ("n", "no", ""):
            return False
        print("Please enter 'y' or 'n'")


def _normalize_config_for_comparison(config: Dict[str, Any]) -> Dict[str, Any]:
    """
    Normalize config by removing fields that shouldn't trigger updates.

    Args:
        config: The config dict to normalize

    Returns:
        Normalized config with only comparison-relevant fields
    """
    # Create a deep copy and remove fields that don't matter for comparison
    normalized = {
        "llm": config.get("llm", {}),
        "wrapper": config.get("wrapper", {}),
    }
    return normalized


def _find_config_differences(old_config: Dict[str, Any], new_config: Dict[str, Any]) -> List[str]:
    """
    Find specific differences between two configs.

    Args:
        old_config: Existing config
        new_config: New config to compare

    Returns:
        List of human-readable differences
    """
    differences = []

    # Compare LLM settings
    old_llm = old_config.get("llm", {})
    new_llm = new_config.get("llm", {})

    if old_llm.get("name") != new_llm.get("name"):
        differences.append(f"provider: {old_llm.get('name', '?')} → {new_llm.get('name', '?')}")

    old_llm_config = old_llm.get("config", {})
    new_llm_config = new_llm.get("config", {})

    if old_llm_config.get("model_name") != new_llm_config.get("model_name"):
        differences.append(f"model: {old_llm_config.get('model_name', '?')} → {new_llm_config.get('model_name', '?')}")

    if old_llm_config.get("api_key") != new_llm_config.get("api_key"):
        old_key = old_llm_config.get("api_key", "?")
        new_key = new_llm_config.get("api_key", "?")
        # Only show env var name, not actual key
        differences.append(f"api_key_env: {old_key} → {new_key}")

    # Compare wrapper settings
    old_wrapper = old_config.get("wrapper", {})
    new_wrapper = new_config.get("wrapper", {})

    if old_wrapper.get("token_threshold") != new_wrapper.get("token_threshold"):
        old_val = old_wrapper.get('token_threshold', '?')
        new_val = new_wrapper.get('token_threshold', '?')
        differences.append(f"threshold: {old_val} → {new_val}")

    if old_wrapper.get("max_iterations") != new_wrapper.get("max_iterations"):
        old_val = old_wrapper.get('max_iterations', '?')
        new_val = new_wrapper.get('max_iterations', '?')
        differences.append(f"max_iterations: {old_val} → {new_val}")

    if old_wrapper.get("llm_timeout") != new_wrapper.get("llm_timeout"):
        old_val = old_wrapper.get('llm_timeout', '?')
        new_val = new_wrapper.get('llm_timeout', '?')
        differences.append(f"llm_timeout: {old_val} → {new_val}")

    return differences


def _should_update_plus_server(  # pylint: disable=too-many-return-statements
    base_name: str,
    existing_servers: Dict[str, Dict[str, Any]],
    config_dir: Path,
    new_proxy_config: Dict[str, Any],
    new_mcp_entry: Dict[str, Any],
) -> Tuple[bool, Optional[str]]:
    """
    Check if a -plus server needs updating by comparing proxy config and mcp.json entry.

    Args:
        base_name: Name of the base server (without -plus suffix)
        existing_servers: All servers from mcp.json
        config_dir: Directory containing proxy configs
        new_proxy_config: The new proxy config that would be written
        new_mcp_entry: The new mcp.json entry that would be written

    Returns:
        Tuple of (should_update, reason):
        - should_update: True if config differs or doesn't exist
        - reason: Human-readable reason for update (or None if no update needed)
    """
    plus_name = f"{base_name}-plus"

    # Check if -plus entry exists in mcp.json
    if plus_name not in existing_servers:
        return True, "new"

    # Check if MCP entry changed (command, args, or env)
    existing_mcp_entry = existing_servers[plus_name]

    # Check command
    if existing_mcp_entry.get("command") != new_mcp_entry.get("command"):
        old_cmd = existing_mcp_entry.get("command", "?")
        new_cmd = new_mcp_entry.get("command", "?")
        # Show just the filename, not full path for readability
        old_py = Path(old_cmd).name if old_cmd else "?"
        new_py = Path(new_cmd).name if new_cmd else "?"
        return True, f"python changed ({old_py} → {new_py})"

    # Check env vars
    old_env = existing_mcp_entry.get("env", {})
    new_env = new_mcp_entry.get("env", {})
    if old_env != new_env:
        # Find what changed
        old_keys = set(old_env.keys())
        new_keys = set(new_env.keys())
        added_keys = new_keys - old_keys
        removed_keys = old_keys - new_keys

        if added_keys:
            return True, f"env vars added ({', '.join(sorted(added_keys)[:2])})"
        if removed_keys:
            return True, f"env vars removed ({', '.join(sorted(removed_keys)[:2])})"
        return True, "env var values changed"

    # Load existing proxy config file
    proxy_config_path = config_dir / f"proxy_{base_name}.json"
    if not proxy_config_path.exists():
        return True, "proxy config missing"

    try:
        existing_proxy = _load_json(proxy_config_path)
    except Exception:  # pylint: disable=broad-exception-caught
        # Catch any JSON parsing or file reading errors
        return True, "proxy config corrupted"

    # Normalize both configs for comparison (only relevant fields)
    old_normalized = _normalize_config_for_comparison(existing_proxy)
    new_normalized = _normalize_config_for_comparison(new_proxy_config)

    # Deep comparison
    if old_normalized == new_normalized:
        return False, None

    # Find specific differences for user-friendly message
    differences = _find_config_differences(existing_proxy, new_proxy_config)

    if differences:
        reason = ", ".join(differences[:2])  # Show first 2 changes
        if len(differences) > 2:
            reason += f" (+{len(differences) - 2} more)"
        return True, reason

    # Generic fallback if we can't determine specific differences
    return True, "config changed"


def _prepare_wrap_changes(
    mcp_config_path: Path,
    servers: Optional[List[str]] = None,
    llm_provider: str = "openai",
    llm_model: str = "gpt-5-mini-2025-08-07",
    llm_api_key_env: str = "OPENAI_API_KEY",
    token_threshold: int = 2000,
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Tuple[Path, Dict[str, Any]]], Optional[str], Dict[str, str]]:
    """
    Prepare the changes that will be made (without writing anything).

    Returns:
        Tuple of (full_config, new_mcp_entries, proxy_configs, api_key_value, update_reasons)
        - full_config: The full mcp.json config with new entries added
        - new_mcp_entries: Just the new server entries to be added
        - proxy_configs: Dict of {server_name: (config_path, config_data)}
        - api_key_value: The API key value from environment (or None)
        - update_reasons: Dict of {base_server_name: reason_string} for tracking updates
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
        base_servers = {k: v for k, v in existing_servers.items() if k in servers}
    else:
        # Get base servers (exclude existing -plus versions from consideration)
        base_servers = {k: v for k, v in existing_servers.items() if not k.endswith("-plus")}

    # Build all proxy configs and MCP entries, then determine which need updating
    all_proxy_configs = {}  # {base_name: proxy_config_dict}
    all_mcp_entries = {}  # {base_name: mcp_entry_dict}
    servers_to_wrap = {}
    update_reasons = {}

    for name, server_cfg in base_servers.items():
        # Build the proxy config for this server
        if "http_url" in server_cfg or "url" in server_cfg:
            url = server_cfg.get("http_url") or server_cfg.get("url", "")
            headers = server_cfg.get("headers", {})
            if not url:
                continue

            proxy_config = _build_proxy_config(
                upstream=name,
                server_name=f"{name}-plus",
                command=None,
                args=None,
                env=None,
                llm_provider=llm_provider,
                llm_model=llm_model,
                llm_api_key_env=llm_api_key_env,
                token_threshold=token_threshold,
                transport="http",
                upstream_url=url,
                headers=headers if headers else None,
            )
        else:
            command = server_cfg.get("command", "")
            args = server_cfg.get("args", [])
            env = server_cfg.get("env", {})
            if not command:
                continue

            proxy_config = _build_proxy_config(
                upstream=name,
                server_name=f"{name}-plus",
                command=command,
                args=args,
                env=env,
                llm_provider=llm_provider,
                llm_model=llm_model,
                llm_api_key_env=llm_api_key_env,
                token_threshold=token_threshold,
                transport="stdio",
            )

        # Store the built configs
        all_proxy_configs[name] = proxy_config

        # Build the MCP entry to compare against existing
        proxy_config_path = config_dir / f"proxy_{name}.json"
        mcp_entry = _build_mcp_entry(
            server_name=f"{name}-plus",
            config_path=proxy_config_path,
            llm_api_key_env=llm_api_key_env,
            llm_api_key_value=api_key_value,
            llm_provider=llm_provider,
        )
        all_mcp_entries[name] = mcp_entry

        # Check if this server needs updating
        should_update, reason = _should_update_plus_server(
            base_name=name,
            existing_servers=existing_servers,
            config_dir=config_dir,
            new_proxy_config=proxy_config,
            new_mcp_entry=mcp_entry,
        )

        if should_update:
            servers_to_wrap[name] = server_cfg
            update_reasons[name] = reason

    if not servers_to_wrap:
        print("No servers to wrap/update (all configurations are up-to-date)", file=sys.stderr)
        sys.exit(0)

    # Load full config to preserve structure
    full_config = _load_json(mcp_config_path)
    if "mcpServers" in full_config:
        servers_section = full_config["mcpServers"]
    else:
        servers_section = full_config

    new_entries = {}
    proxy_configs = {}

    # Use the already-built configs (built above during comparison phase)
    # This avoids rebuilding configs twice and ensures what we compared is what we write
    for name in servers_to_wrap:
        plus_name = f"{name}-plus"

        # Get the pre-built proxy config and MCP entry (already built during comparison)
        proxy_config = all_proxy_configs[name]
        proxy_config_path = config_dir / f"proxy_{name}.json"
        proxy_configs[plus_name] = (proxy_config_path, proxy_config)

        # Get the pre-built MCP entry (already has correct Python path from sys.executable)
        mcp_entry = all_mcp_entries[name]
        new_entries[plus_name] = mcp_entry

    # Add new entries to config (in memory only)
    servers_section.update(new_entries)

    return full_config, new_entries, proxy_configs, api_key_value, update_reasons


def wrap_servers(
    mcp_config_path: Path,
    servers: Optional[List[str]] = None,
    llm_provider: str = "openai",
    llm_model: str = "gpt-5-mini-2025-08-07",
    llm_api_key_env: str = "OPENAI_API_KEY",
    token_threshold: int = 2000,
    dry_run: bool = False,
    yes: bool = False,
    output_path: Optional[Path] = None,
) -> Dict[str, Any]:
    """
    Wrap MCP servers from a config file.

    Args:
        mcp_config_path: Path to the mcp.json file
        servers: List of server names to wrap (None = all)
        llm_provider: LLM provider name (openai, gemini, anthropic, etc.)
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
    full_config, new_entries, proxy_configs, api_key_value, update_reasons = _prepare_wrap_changes(
        mcp_config_path=mcp_config_path,
        servers=servers,
        llm_provider=llm_provider,
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

    # Python interpreter info
    print(f"\n[Python] Using: {sys.executable}")
    print("         This Python will be used to run proxy servers.")

    # API key status
    if api_key_value:
        print(f"\n[API Key] Found {llm_api_key_env} in environment.")
        print("          Will embed in config (keep mcp.json secure).")
    else:
        print(f"\n[API Key] Warning: {llm_api_key_env} not found in environment.")
        print(f"          Will use ${llm_api_key_env} reference.")

    # Show proxy configs that will be created/updated
    print(f"\n[Proxy Configs] Will create/update {len(proxy_configs)} file(s) in ~/.mcpplus/configs/:")
    for server_name, (config_path, _) in proxy_configs.items():
        base_name = server_name.replace("-plus", "")
        reason = update_reasons.get(base_name, "unknown")

        if reason == "new":
            print(f"  ✨ {config_path.name} (new)")
        else:
            print(f"  🔄 {config_path.name} (update: {reason})")

    # Show entries that will be added/updated in mcp.json
    new_count = sum(1 for r in update_reasons.values() if r == "new")
    update_count = len(update_reasons) - new_count

    if new_count > 0 and update_count > 0:
        action_desc = f"add {new_count} new and update {update_count} existing"
    elif new_count > 0:
        action_desc = f"add {new_count}"
    else:
        action_desc = f"update {update_count}"

    print(f"\n[MCP Config] Will {action_desc} server(s) in {output}:")
    print("-" * 60)
    print(json.dumps(new_entries, indent=2))
    print("-" * 60)

    # Explain what each -plus server does
    print("\n[What This Does]")
    print("  Each '-plus' server wraps the original server with intelligent")
    print("  output filtering. Long tool outputs are processed by an LLM to")
    print("  extract only the information relevant to your query.")
    print(f"\n  LLM Provider: {llm_provider}")
    print(f"  LLM Model: {llm_model}")
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
    for server_name, (config_path, proxy_config) in proxy_configs.items():
        _write_json(config_path, proxy_config)
        base_name = server_name.replace("-plus", "")
        reason = update_reasons.get(base_name, "unknown")

        if reason == "new":
            print(f"  ✨ Created: {config_path}")
        else:
            print(f"  🔄 Updated: {config_path}")

    # Write updated mcp.json
    _write_json(output, full_config)
    print(f"  Updated: {output}")

    new_count = sum(1 for r in update_reasons.values() if r == "new")
    update_count = len(update_reasons) - new_count

    if new_count > 0 and update_count > 0:
        print(f"\nSuccess! Created {new_count} and updated {update_count} wrapped server(s).")
    elif new_count > 0:
        print(f"\nSuccess! Created {new_count} wrapped server(s).")
    else:
        print(f"\nSuccess! Updated {update_count} wrapped server(s).")
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
        "--llm-provider",
        default="openai",
        help="LLM provider: openai, gemini, anthropic, etc. (default: openai)",
    )
    parser.add_argument(
        "--llm-model",
        default="gpt-5-mini-2025-08-07",
        help="LLM model for post-processing (default: gpt-5-mini)",
    )
    parser.add_argument(
        "--llm-api-key-env",
        default="OPENAI_API_KEY",
        help="Env var name for LLM API key (default: OPENAI_API_KEY)",
    )
    parser.add_argument(
        "--token-threshold",
        type=int,
        default=2000,
        help="Min tokens to trigger post-processing (default: 2000)",
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
        llm_provider=args.llm_provider,
        llm_model=args.llm_model,
        llm_api_key_env=args.llm_api_key_env,
        token_threshold=args.token_threshold,
        dry_run=args.dry_run,
        yes=args.yes,
        output_path=output_path,
    )


if __name__ == "__main__":
    main()
