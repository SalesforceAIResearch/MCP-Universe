#!/usr/bin/env python3
"""
PostgreSQL Database Preparation Script for MCPMark Benchmarks
==============================================================

This script prepares the PostgreSQL environment for running mcpmark postgres benchmarks.
It performs the following tasks:
1. Starts Docker PostgreSQL container if not running
2. Downloads database backups if not present
3. Creates databases and restores from backups
4. Verifies successful import

Usage:
    python prepare_postgres.py [--force-download]
"""

import os
import sys
import argparse
import logging
import subprocess
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple
import urllib.request
import urllib.error

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

# Configuration
CONTAINER_NAME = "mcpmark-postgres"
POSTGRES_USER = "postgres"
POSTGRES_PASSWORD = "password"
POSTGRES_PORT = 5432
POSTGRES_IMAGE = "postgres:17-alpine"

# Database configurations
DATABASES = {
    "chinook": {
        "url": "https://storage.mcpmark.ai/postgres/chinook.backup",
        "filename": "chinook.backup"
    },
    "employees": {
        "url": "https://storage.mcpmark.ai/postgres/employees.backup",
        "filename": "employees.backup"
    },
    "dvdrental": {
        "url": "https://storage.mcpmark.ai/postgres/dvdrental.backup",
        "filename": "dvdrental.backup"
    },
    "sports": {
        "url": "https://storage.mcpmark.ai/postgres/sports.backup",
        "filename": "sports.backup"
    }
}

# Paths
SCRIPT_DIR = Path(__file__).parent
PROJECT_ROOT = SCRIPT_DIR.parent.parent
DATA_DIR = PROJECT_ROOT / "tests" / "data" / "postgres"


def run_command(
    cmd: List[str],
    check: bool = True,
    capture_output: bool = True,
    env: Optional[Dict[str, str]] = None,
) -> subprocess.CompletedProcess:
    """Run a shell command and return the result."""
    try:
        result = subprocess.run(
            cmd,
            check=check,
            capture_output=capture_output,
            text=True,
            env=env or os.environ.copy(),
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


def check_container_exists(container_name: str) -> bool:
    """Check if a Docker container exists."""
    result = run_command(
        [
            "docker",
            "ps",
            "-a",
            "--filter",
            f"name={container_name}",
            "--format",
            "{{.Names}}",
        ]
    )
    return container_name in result.stdout.strip()


def check_container_running(container_name: str) -> bool:
    """Check if a Docker container is running."""
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
    return container_name in result.stdout.strip()


def start_postgres_container() -> bool:
    """Start PostgreSQL Docker container."""
    logger.info("🔍 Checking PostgreSQL container status...")

    if check_container_exists(CONTAINER_NAME):
        if check_container_running(CONTAINER_NAME):
            logger.info("✅ Container '%s' is already running", CONTAINER_NAME)
            return True
        logger.info("▶️  Starting existing container '%s'...", CONTAINER_NAME)
        run_command(["docker", "start", CONTAINER_NAME])
        logger.info("✅ Container started")
        return True

    logger.info("🐳 Creating new PostgreSQL container '%s'...", CONTAINER_NAME)
    run_command(
        [
            "docker",
            "run",
            "-d",
            "--name",
            CONTAINER_NAME,
            "-e",
            f"POSTGRES_PASSWORD={POSTGRES_PASSWORD}",
            "-e",
            f"POSTGRES_USER={POSTGRES_USER}",
            "-p",
            f"{POSTGRES_PORT}:5432",
            POSTGRES_IMAGE,
        ]
    )
    logger.info("✅ Container created and started")
    return True


def wait_for_postgres(max_attempts: int = 30) -> bool:
    """Wait for PostgreSQL to be ready."""
    logger.info("⏳ Waiting for PostgreSQL to be ready...")
    env = os.environ.copy()
    env["PGPASSWORD"] = POSTGRES_PASSWORD

    for attempt in range(max_attempts):
        try:
            result = run_command(
                ["psql", "-h", "localhost", "-U", POSTGRES_USER, "-c", "SELECT 1;"],
                check=False,
                env=env
            )
            if result.returncode == 0:
                logger.info("✅ PostgreSQL is ready")
                return True
        except (subprocess.SubprocessError, OSError):
            pass

        time.sleep(1)
        if (attempt + 1) % 5 == 0:
            logger.info("   Still waiting... (%s/%s)", attempt + 1, max_attempts)

    logger.error("❌ PostgreSQL failed to start within the timeout period")
    return False


def download_database_backup(db_name: str, url: str, filepath: Path, force: bool = False) -> bool:
    """Download database backup file."""
    if filepath.exists() and not force:
        logger.info("⏭️  Backup already exists: %s", filepath.name)
        return True

    logger.info("📥 Downloading %s database backup from %s...", db_name, url)
    try:
        urllib.request.urlretrieve(url, str(filepath))

        if filepath.exists() and filepath.stat().st_size > 0:
            size_mb = filepath.stat().st_size / (1024 * 1024)
            logger.info("✅ Downloaded: %s (%.2f MB)", filepath.name, size_mb)
            return True
        logger.error("❌ Download failed or file is empty: %s", filepath.name)
        return False
    except (urllib.error.URLError, OSError) as exc:
        logger.error("❌ Failed to download %s: %s", db_name, exc)
        if filepath.exists():
            filepath.unlink()  # Remove partial download
        return False


def database_exists(db_name: str) -> bool:
    """Check if a database exists."""
    env = os.environ.copy()
    env["PGPASSWORD"] = POSTGRES_PASSWORD

    result = run_command(
        ["psql", "-h", "localhost", "-U", POSTGRES_USER, "-lqt"],
        check=False,
        env=env
    )
    return db_name in result.stdout


def create_database(db_name: str) -> bool:
    """Create a PostgreSQL database."""
    env = os.environ.copy()
    env["PGPASSWORD"] = POSTGRES_PASSWORD

    if database_exists(db_name):
        logger.info("⏭️  Database '%s' already exists", db_name)
        return True

    logger.info("🔨 Creating database '%s'...", db_name)
    try:
        run_command(
            ["createdb", "-h", "localhost", "-U", POSTGRES_USER, db_name],
            env=env
        )
        logger.info("✅ Database '%s' created", db_name)
        return True
    except (subprocess.SubprocessError, OSError) as exc:
        logger.error("❌ Failed to create database '%s': %s", db_name, exc)
        return False


def restore_database(db_name: str, backup_file: Path) -> bool:
    """Restore database from backup file using Docker container's pg_restore."""
    if not backup_file.exists():
        logger.error("❌ Backup file not found: %s", backup_file)
        return False

    logger.info("📦 Restoring '%s' from %s...", db_name, backup_file.name)

    try:
        # Copy backup file into container
        logger.debug("Copying backup file to container...")
        env = os.environ.copy()
        copy_result = run_command(
            [
                "docker",
                "cp",
                str(backup_file),
                f"{CONTAINER_NAME}:/tmp/{backup_file.name}",
            ],
            check=False,
            env=env
        )

        if copy_result.returncode != 0:
            logger.error("❌ Failed to copy backup file to container")
            return False

        # Run pg_restore inside the container
        env = os.environ.copy()
        env["PGPASSWORD"] = POSTGRES_PASSWORD
        restore_result = run_command(
            [
                "docker",
                "exec",
                "-e",
                f"PGPASSWORD={POSTGRES_PASSWORD}",
                CONTAINER_NAME,
                "pg_restore",
                "-h",
                "localhost",
                "-U",
                POSTGRES_USER,
                "-d",
                db_name,
                "-v",
                f"/tmp/{backup_file.name}",
            ],
            check=False,
            env=env
        )

        # Check if there are any tables created (check all schemas, not just public)
        env = os.environ.copy()
        env["PGPASSWORD"] = POSTGRES_PASSWORD
        table_count_query = (
            "SELECT COUNT(*) FROM information_schema.tables "
            "WHERE table_schema NOT IN ('pg_catalog', 'information_schema');"
        )
        count_result = run_command(
            [
                "psql",
                "-h",
                "localhost",
                "-U",
                POSTGRES_USER,
                "-d",
                db_name,
                "-t",
                "-c",
                table_count_query,
            ],
            check=False,
            env=env
        )
        table_count = int(count_result.stdout.strip()) if count_result.returncode == 0 else 0

        # Clean up backup file from container
        run_command(
            ["docker", "exec", CONTAINER_NAME, "rm", f"/tmp/{backup_file.name}"],
            check=False,
            env=env
        )

        if table_count > 0:
            if restore_result.returncode != 0:
                # Check if there are real errors (not just warnings about duplicates)
                stderr_lower = restore_result.stderr.lower()
                has_real_errors = any(
                    err in stderr_lower for err in ["fatal", "could not", "failed to"]
                )

                if has_real_errors:
                    logger.warning(
                        "⚠️  Database '%s' restored with warnings (%s tables created)",
                        db_name,
                        table_count,
                    )
                    logger.debug("Restore warnings: %s", restore_result.stderr[:500])
                else:
                    logger.info(
                        "✅ Database '%s' restored successfully (%s tables)",
                        db_name,
                        table_count,
                    )
            else:
                logger.info(
                    "✅ Database '%s' restored successfully (%s tables)",
                    db_name,
                    table_count,
                )
            return True

        logger.error("❌ Failed to restore database '%s' - no tables created", db_name)
        if restore_result.stderr:
            logger.error("Error details: %s", restore_result.stderr)
        return False
    except (subprocess.SubprocessError, OSError, ValueError) as exc:
        logger.error("❌ Error restoring database '%s': %s", db_name, exc)
        return False


def verify_database(db_name: str) -> Tuple[bool, int]:
    """Verify database has been imported correctly."""
    env = os.environ.copy()
    env["PGPASSWORD"] = POSTGRES_PASSWORD

    try:
        # Count tables (check all schemas, not just public)
        table_count_query = (
            "SELECT COUNT(*) FROM information_schema.tables "
            "WHERE table_schema NOT IN ('pg_catalog', 'information_schema');"
        )
        result = run_command(
            [
                "psql",
                "-h",
                "localhost",
                "-U",
                POSTGRES_USER,
                "-d",
                db_name,
                "-t",
                "-c",
                table_count_query,
            ],
            env=env
        )

        table_count = int(result.stdout.strip())

        if table_count > 0:
            logger.info("✅ Verified '%s': %s tables", db_name, table_count)
            return True, table_count
        logger.error("❌ Database '%s' has no tables", db_name)
        return False, 0
    except (ValueError, subprocess.SubprocessError, OSError) as exc:
        logger.error("❌ Failed to verify database '%s': %s", db_name, exc)
        return False, 0


def determine_databases(selection: List[str]) -> List[str]:
    """Resolve list of databases to prepare based on CLI selection."""
    return list(DATABASES.keys()) if "all" in selection else selection


def download_backups(databases: List[str], force_download: bool) -> Dict[str, bool]:
    """Download all requested database backups."""
    download_success: Dict[str, bool] = {}
    for db_name in databases:
        db_config = DATABASES[db_name]
        filepath = DATA_DIR / db_config["filename"]
        download_success[db_name] = download_database_backup(
            db_name, db_config["url"], filepath, force_download
        )
    return download_success


def create_and_restore(databases: List[str]) -> Dict[str, bool]:
    """Create PostgreSQL databases and restore backups."""
    restore_success: Dict[str, bool] = {}
    for db_name in databases:
        db_config = DATABASES[db_name]
        backup_file = DATA_DIR / db_config["filename"]

        if not create_database(db_name):
            restore_success[db_name] = False
            continue

        restore_success[db_name] = restore_database(db_name, backup_file)
    return restore_success


def verify_databases(
    databases: List[str],
    restore_success: Dict[str, bool],
) -> Dict[str, Tuple[bool, int]]:
    """Verify databases that were restored successfully."""
    verify_results: Dict[str, Tuple[bool, int]] = {}
    for db_name in databases:
        if restore_success.get(db_name, False):
            verify_results[db_name] = verify_database(db_name)
        else:
            verify_results[db_name] = (False, 0)
    return verify_results


def log_summary(verify_results: Dict[str, Tuple[bool, int]]) -> bool:
    """Log summary of verification results and return overall success flag."""
    logger.info("%s", "\n" + "=" * 60)
    logger.info("📊 Summary")
    logger.info("%s", "=" * 60)

    all_successful = True
    for db_name, (success, table_count) in verify_results.items():
        status = "✅" if success else "❌"
        if not success:
            all_successful = False
        logger.info("%s %s - %3s tables", status, f"{db_name:12}", table_count)

    logger.info("%s", "-" * 60)
    return all_successful


def main() -> int:
    """CLI entry point for preparing PostgreSQL databases."""
    parser = argparse.ArgumentParser(
        description="Prepare PostgreSQL databases for MCPMark benchmarks"
    )
    parser.add_argument(
        "--force-download",
        action="store_true",
        help="Force re-download of database backups",
    )
    parser.add_argument(
        "--databases",
        nargs="+",
        choices=list(DATABASES.keys()) + ["all"],
        default=["all"],
        help="Specify which databases to prepare",
    )
    args = parser.parse_args()

    databases_to_prepare = determine_databases(args.databases)

    logger.info("%s", "=" * 60)
    logger.info("PostgreSQL Database Preparation for MCPMark")
    logger.info("%s", "=" * 60)

    # Step 1: Check Docker and start container
    logger.info("\n📋 Step 1: Starting PostgreSQL Container")
    logger.info("%s", "-" * 60)

    if not check_docker_running():
        logger.error("❌ Docker is not running. Please start Docker and try again.")
        return 1

    if not start_postgres_container():
        logger.error("❌ Failed to start PostgreSQL container")
        return 1

    if not wait_for_postgres():
        logger.error("❌ PostgreSQL is not responding")
        return 1

    # Step 2: Download database backups
    logger.info("\n📋 Step 2: Downloading Database Backups")
    logger.info("%s", "-" * 60)

    DATA_DIR.mkdir(parents=True, exist_ok=True)

    download_success = download_backups(databases_to_prepare, args.force_download)

    if not all(download_success.values()):
        logger.error("❌ Some database backups failed to download")
        failed = [name for name, success in download_success.items() if not success]
        logger.error("   Failed: %s", ", ".join(failed))
        return 1

    # Step 3: Create databases and restore
    logger.info("\n📋 Step 3: Creating Databases and Restoring from Backups")
    logger.info("%s", "-" * 60)

    restore_success = create_and_restore(databases_to_prepare)

    # Step 4: Verify databases
    logger.info("\n📋 Step 4: Verifying Database Imports")
    logger.info("%s", "-" * 60)

    verify_results = verify_databases(databases_to_prepare, restore_success)
    all_successful = log_summary(verify_results)

    if all_successful:
        logger.info("✅ All databases prepared successfully!")
        logger.info("\n📝 PostgreSQL Configuration:")
        logger.info("   Host: localhost")
        logger.info("   Port: %s", POSTGRES_PORT)
        logger.info("   User: %s", POSTGRES_USER)
        logger.info("   Password: %s", POSTGRES_PASSWORD)
        logger.info("   Databases: %s", ", ".join(databases_to_prepare))
        logger.info("\n🚀 You can now run the mcpmark postgres benchmarks!")
        return 0

    logger.error("❌ Some databases failed to prepare")
    failed = [name for name, (success, _) in verify_results.items() if not success]
    logger.error("   Failed: %s", ", ".join(failed))
    return 1


if __name__ == "__main__":
    sys.exit(main())
