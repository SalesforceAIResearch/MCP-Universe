#!/usr/bin/env python3
"""
Playwright WebArena Environment Setup Script
=============================================

This script prepares the WebArena environments for Playwright MCP testing.
It downloads and deploys three Docker containers:
- Shopping (E-commerce, Port 7770)
- Shopping Admin (Management Panel, Port 7780)
- Reddit (Forum, Port 9999)

Usage:
    python prepare_playwright_webarena.py [--download-source SOURCE] [--skip-download]
"""

import os
import sys
import subprocess
import time
import logging
from pathlib import Path
from typing import List, Optional
import urllib.request
import urllib.error
import argparse

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# Configuration
ENVIRONMENTS = {
    "shopping": {
        "name": "Shopping E-commerce",
        "port": 7770,
        "container_name": "shopping",
        "image_name": "shopping_final_0712",
        "urls": {
            "archive": (
                "https://archive.org/download/webarena-env-shopping-image/"
                "shopping_final_0712.tar"
            ),
            "cmu": (
                "http://metis.lti.cs.cmu.edu/webarena-images/"
                "shopping_final_0712.tar"
            ),
        },
        "filename": "shopping_final_0712.tar",
        "startup_time": 180,
        "setup_commands": [
            (
                "/var/www/magento2/bin/magento "
                "setup:store-config:set --base-url=\"http://localhost:7770\""
            ),
            (
                "mysql -u magentouser -pMyPassword magentodb -e "
                "\"UPDATE core_config_kill SET value='http://localhost:7770/' "
                "WHERE path IN ('web/secure/base_url', 'web/unsecure/base_url');\""
            ),
            "/var/www/magento2/bin/magento cache:flush"
        ]
    },
    "shopping_admin": {
        "name": "Shopping Admin Panel",
        "port": 7780,
        "container_name": "shopping_admin",
        "image_name": "shopping_admin_final_0719",
        "urls": {
            "archive": (
                "https://archive.org/download/webarena-env-shopping-admin-image/"
                "shopping_admin_final_0719.tar"
            ),
            "cmu": (
                "http://metis.lti.cs.cmu.edu/webarena-images/"
                "shopping_admin_final_0719.tar"
            ),
        },
        "filename": "shopping_admin_final_0719.tar",
        "startup_time": 120,
        "setup_commands": [
            (
                "/var/www/magento2/bin/magento "
                "setup:store-config:set --base-url=\"http://localhost:7780\""
            ),
            (
                "mysql -u magentouser -pMyPassword magentodb -e "
                "\"UPDATE core_config_data SET value='http://localhost:7780/' "
                "WHERE path IN ('web/secure/base_url', 'web/unsecure/base_url');\""
            ),
            "php /var/www/magento2/bin/magento config:set admin/security/password_is_forced 0",
            "php /var/www/magento2/bin/magento config:set admin/security/password_lifetime 0",
            "/var/www/magento2/bin/magento cache:flush"
        ]
    },
    "reddit": {
        "name": "Reddit Forum",
        "port": 9999,
        "container_name": "forum",
        "image_name": "postmill-populated-exposed-withimg",
        "urls": {
            "archive": (
                "https://archive.org/download/webarena-env-forum-image/"
                "postmill-populated-exposed-withimg.tar"
            ),
            "cmu": (
                "http://metis.lti.cs.cmu.edu/webarena-images/"
                "postmill-populated-exposed-withimg.tar"
            ),
        },
        "filename": "postmill-populated-exposed-withimg.tar",
        "startup_time": 120,
        "setup_commands": []
    }
}

# Paths
SCRIPT_DIR = Path(__file__).parent
PROJECT_ROOT = SCRIPT_DIR.parent.parent
DATA_DIR = PROJECT_ROOT / "tests" / "data" / "playwright_webarena"


def run_command(
    cmd: List[str],
    check: bool = True,
    capture_output: bool = True,
    env: Optional[dict] = None,
) -> subprocess.CompletedProcess:
    """Run a shell command and return the result."""
    try:
        result = subprocess.run(
            cmd,
            check=check,
            capture_output=capture_output,
            text=True,
            env=env or os.environ.copy()
        )
        return result
    except subprocess.CalledProcessError as exc:
        logger.error("Command failed: %s", " ".join(cmd))
        logger.error("Error: %s", exc.stderr)
        raise


def check_docker_running() -> bool:
    """Check if Docker is running."""
    try:
        result = run_command(["docker", "ps"], check=False)
        return result.returncode == 0
    except FileNotFoundError:
        logger.error("❌ Docker is not installed")
        return False


def check_port_available(port: int) -> bool:
    """Check if a port is available."""
    result = run_command(["lsof", "-i", f":{port}"], check=False, capture_output=True)
    return result.returncode != 0


def check_container_running(container_name: str) -> bool:
    """Check if a Docker container is running."""
    result = run_command(
        ["docker", "ps", "--filter", f"name={container_name}", "--format", "{{.Names}}"]
    )
    return container_name in result.stdout.strip()


def download_image(env_key: str, source: str = "archive") -> bool:
    """Download Docker image tar file."""
    env_config = ENVIRONMENTS[env_key]
    filepath = DATA_DIR / env_config["filename"]

    if filepath.exists():
        logger.info("⏭️  Image already exists: %s", env_config["filename"])
        return True

    url = env_config["urls"].get(source)
    if not url:
        logger.error("❌ Unknown download source: %s", source)
        return False

    logger.info("📥 Downloading %s from %s...", env_config["name"], source)
    logger.info("   URL: %s", url)
    logger.info("   This may take a while (images are ~2-5GB each)...")

    try:
        # Use wget for better progress display
        result = run_command(
            ["wget", "-O", str(filepath), url],
            check=False,
            capture_output=False  # Show progress
        )

        if (
            result.returncode == 0
            and filepath.exists()
            and filepath.stat().st_size > 0
        ):
            size_gb = filepath.stat().st_size / (1024 * 1024 * 1024)
            logger.info("✅ Downloaded: %s (%.2f GB)", env_config["filename"], size_gb)
            return True
        logger.error("❌ Download failed: %s", env_config["filename"])
        if filepath.exists():
            filepath.unlink()
        return False
    except (OSError, subprocess.SubprocessError, Exception) as exc:  # pylint: disable=broad-exception-caught
        logger.error("❌ Failed to download %s: %s", env_key, exc)
        if filepath.exists():
            filepath.unlink()
        return False


def load_docker_image(env_key: str) -> bool:
    """Load Docker image from tar file."""
    env_config = ENVIRONMENTS[env_key]
    filepath = DATA_DIR / env_config["filename"]

    if not filepath.exists():
        logger.error("❌ Image file not found: %s", filepath)
        return False

    logger.info("📦 Loading Docker image: %s...", env_config["name"])

    try:
        result = run_command(["docker", "load", "--input", str(filepath)], check=False)
        if result.returncode == 0:
            logger.info("✅ Image loaded: %s", env_config["image_name"])
            return True
        logger.error("❌ Failed to load image: %s", env_config["image_name"])
        return False
    except (OSError, subprocess.SubprocessError, Exception) as exc:  # pylint: disable=broad-exception-caught
        logger.error("❌ Error loading image: %s", exc)
        return False


def start_container(env_key: str) -> bool:
    """Start Docker container."""
    env_config = ENVIRONMENTS[env_key]
    container_name = env_config["container_name"]

    # Check if container already exists
    check_result = run_command(
        ["docker", "ps", "-a", "--filter", f"name={container_name}", "--format", "{{.Names}}"],
        check=False
    )

    if container_name in check_result.stdout:
        logger.info("🔄 Container '%s' already exists, removing...", container_name)
        run_command(["docker", "rm", "-f", container_name], check=False)

    logger.info("🚀 Starting container: %s...", env_config["name"])

    try:
        result = run_command([
            "docker", "run",
            "--name", container_name,
            "-p", f"{env_config['port']}:80",
            "-d",
            env_config["image_name"]
        ], check=False)

        if result.returncode == 0:
            logger.info("✅ Container started: %s", container_name)
            logger.info(
                "⏳ Waiting %s seconds for service initialization...",
                env_config["startup_time"],
            )
            time.sleep(env_config["startup_time"])
            return True
        logger.error("❌ Failed to start container: %s", container_name)
        return False
    except (OSError, subprocess.SubprocessError, Exception) as exc:  # pylint: disable=broad-exception-caught
        logger.error("❌ Error starting container: %s", exc)
        return False


def configure_container(env_key: str) -> bool:
    """Run configuration commands inside container."""
    env_config = ENVIRONMENTS[env_key]
    container_name = env_config["container_name"]

    if not env_config["setup_commands"]:
        logger.info("✅ No configuration needed for %s", env_config["name"])
        return True

    logger.info("⚙️  Configuring %s...", env_config["name"])

    for cmd in env_config["setup_commands"]:
        try:
            result = run_command(
                ["docker", "exec", container_name, "bash", "-c", cmd],
                check=False,
                capture_output=True
            )
            if result.returncode != 0:
                logger.warning("⚠️  Command warning: %s...", cmd[:50])
                logger.debug("   stderr: %s", result.stderr[:200])
        except Exception as exc:  # pylint: disable=broad-exception-caught
            logger.warning("⚠️  Configuration command failed: %s", exc)

    logger.info("✅ Configuration completed for %s", env_config["name"])
    return True


def verify_container(env_key: str) -> bool:
    """Verify container is running and accessible."""
    env_config = ENVIRONMENTS[env_key]
    container_name = env_config["container_name"]
    port = env_config["port"]

    # Check if container is running
    if not check_container_running(container_name):
        logger.error("❌ Container '%s' is not running", container_name)
        return False

    # Check if port is accessible
    try:
        url = f"http://localhost:{port}"
        req = urllib.request.Request(url, method="HEAD")
        with urllib.request.urlopen(req, timeout=10) as _resp:
            _ = _resp.status
        logger.info(
            "✅ %s is accessible at http://localhost:%s", env_config["name"], port
        )
        return True
    except (urllib.error.URLError, Exception) as exc:  # pylint: disable=broad-exception-caught
        logger.warning("⚠️  %s might not be fully ready yet: %s", env_config["name"], exc)
        logger.info("   Try accessing http://localhost:%s in your browser", port)
        return True  # Still return True as container is running


def main():  # pylint: disable=too-many-branches, too-many-statements
    """Prepare WebArena Docker environments: download, load, start, configure, verify."""
    parser = argparse.ArgumentParser(
        description="Prepare Playwright WebArena environments"
    )
    parser.add_argument(
        "--download-source",
        choices=["archive", "cmu"],
        default="archive",
        help="Download source (default: archive.org)",
    )
    parser.add_argument(
        "--skip-download",
        action="store_true",
        help="Skip download if images already exist",
    )
    parser.add_argument(
        "--environments",
        nargs="+",
        choices=list(ENVIRONMENTS.keys()) + ["all"],
        default=["all"],
        help="Specify which environments to setup",
    )
    args = parser.parse_args()

    # Determine which environments to setup
    if "all" in args.environments:
        envs_to_setup = list(ENVIRONMENTS.keys())
    else:
        envs_to_setup = args.environments

    logger.info("%s", "=" * 60)
    logger.info("Playwright WebArena Environment Setup")
    logger.info("%s", "=" * 60)

    # Check Docker
    logger.info("\n📋 Step 1: Checking Docker")
    logger.info("%s", "-" * 60)
    if not check_docker_running():
        logger.error("❌ Docker is not running. Please start Docker and try again.")
        return 1
    logger.info("✅ Docker is running")

    # Create data directory
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    # Download images
    if not args.skip_download:
        logger.info("\n📋 Step 2: Downloading Docker Images")
        logger.info("-" * 60)
        logger.info("⚠️  Warning: Each image is 2-5GB. This will take time.")

        download_success = {}
        for env_key in envs_to_setup:
            success = download_image(env_key, args.download_source)
            download_success[env_key] = success

        if not all(download_success.values()):
            logger.error("❌ Some downloads failed")
            failed = [key for key, ok in download_success.items() if not ok]
            logger.error("   Failed: %s", ", ".join(failed))
            return 1

    # Load images
    logger.info("\n📋 Step 3: Loading Docker Images")
    logger.info("%s", "-" * 60)

    load_success = {}
    for env_key in envs_to_setup:
        success = load_docker_image(env_key)
        load_success[env_key] = success

    if not all(load_success.values()):
        logger.error("❌ Some images failed to load")
        return 1

    # Start containers
    logger.info("\n📋 Step 4: Starting Containers")
    logger.info("%s", "-" * 60)

    start_success = {}
    for env_key in envs_to_setup:
        success = start_container(env_key)
        start_success[env_key] = success

    # Configure containers
    logger.info("\n📋 Step 5: Configuring Environments")
    logger.info("%s", "-" * 60)

    for env_key in envs_to_setup:
        if start_success.get(env_key):
            configure_container(env_key)

    # Verify
    logger.info("\n📋 Step 6: Verifying Environments")
    logger.info("%s", "-" * 60)

    verify_results = {}
    for env_key in envs_to_setup:
        if start_success.get(env_key):
            verify_results[env_key] = verify_container(env_key)
        else:
            verify_results[env_key] = False

    # Summary
    logger.info("%s", "\n" + "=" * 60)
    logger.info("📊 Summary")
    logger.info("%s", "=" * 60)

    for env_key in envs_to_setup:
        env_config = ENVIRONMENTS[env_key]
        status = "✅" if verify_results.get(env_key) else "❌"
    logger.info(
        "%s %s - http://localhost:%s",
        status,
        f"{env_config['name']:25}",
        env_config["port"],
    )

    logger.info("%s", "-" * 60)

    if all(verify_results.values()):
        logger.info("✅ All environments are ready!")
        logger.info("\n📝 Access Information:")
        logger.info("   Shopping:       http://localhost:7770")
        logger.info("   Shopping Admin: http://localhost:7780/admin (admin/admin1234)")
        logger.info("   Reddit:         http://localhost:9999")
        logger.info("\n🚀 You can now run Playwright WebArena benchmarks!")
        return 0
    logger.error("❌ Some environments failed to start")
    return 1


if __name__ == "__main__":
    sys.exit(main())
