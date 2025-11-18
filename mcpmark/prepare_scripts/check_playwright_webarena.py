#!/usr/bin/env python3
"""
Quick Playwright WebArena Status Check Script
==============================================

This script quickly checks the status of WebArena environments.

Usage:
    python check_playwright_webarena.py
"""

import subprocess
import sys
import urllib.error
import urllib.request
from typing import Dict, Optional, Union

ENVIRONMENTS: Dict[str, Dict[str, Union[int, str]]] = {
    "shopping": {"port": 7770, "name": "Shopping E-commerce"},
    "shopping_admin": {"port": 7780, "name": "Shopping Admin"},
    "forum": {"port": 9999, "name": "Reddit Forum"}
}


def run_command(
    cmd,
    check: bool = False,
    capture_output: bool = True,
) -> Optional[subprocess.CompletedProcess]:
    """Run a shell command."""
    try:
        return subprocess.run(
            cmd,
            check=check,
            capture_output=capture_output,
            text=True,
        )
    except (subprocess.SubprocessError, OSError):
        return None


def check_docker():
    """Check if Docker is running."""
    result = run_command(["docker", "ps"])
    return result and result.returncode == 0


def check_container_running(container_name):
    """Check if container is running."""
    result = run_command(
        [
            "docker",
            "ps",
            "--filter",
            f"name={container_name}",
            "--format",
            "{{.Names}}",
        ]
    )
    return result and container_name in result.stdout


def check_port_accessible(port):
    """Check if port is accessible."""
    try:
        url = f"http://localhost:{port}"
        req = urllib.request.Request(url, method="HEAD")
        with urllib.request.urlopen(req, timeout=5):
            pass
        return True
    except urllib.error.URLError:
        return False


def main():
    """Check Docker containers and ports for Playwright WebArena environments."""
    print("🔍 Playwright WebArena Status Check")
    print("=" * 60)
    print()

    # Check Docker
    print("📦 Docker Status:")
    if check_docker():
        print("   ✅ Docker is running")
    else:
        print("   ❌ Docker is not running")
        print("\n💡 Please start Docker and run setup:")
        print("   ./mcpmark/prepare_scripts/setup_playwright_webarena.sh")
        return 1

    # Check Containers
    print("\n🐳 Container Status:")
    all_ok = True

    for container_name, config in ENVIRONMENTS.items():
        running = check_container_running(container_name)
        accessible = check_port_accessible(config["port"]) if running else False

        if running and accessible:
            print(f"   ✅ {config['name']:25} - http://localhost:{config['port']}")
        elif running:
            print(f"   ⚠️  {config['name']:25} - Container running but not accessible")
        else:
            print(f"   ❌ {config['name']:25} - Not running")
            all_ok = False

    print("\n" + "=" * 60)

    if all_ok:
        print("✅ All WebArena environments are ready!")
        print("\n🚀 You can now run:")
        print("   python tests/benchmark/test_benchmark_mcpmark_playwright_webarena.py")
        return 0

    print("❌ Some environments are not ready")
    print("\n💡 Run setup to prepare all environments:")
    print("   ./mcpmark/prepare_scripts/setup_playwright_webarena.sh")
    return 1


if __name__ == "__main__":
    sys.exit(main())
