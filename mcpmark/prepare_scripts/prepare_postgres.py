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
import subprocess
import time
import logging
from pathlib import Path
from typing import List, Tuple
import argparse

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
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


def run_command(cmd: List[str], check=True, capture_output=True, env=None) -> subprocess.CompletedProcess:
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
    except subprocess.CalledProcessError as e:
        logger.error(f"Command failed: {' '.join(cmd)}")
        logger.error(f"Error: {e.stderr}")
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
    result = run_command(["docker", "ps", "-a", "--filter", f"name={container_name}", "--format", "{{.Names}}"])
    return container_name in result.stdout.strip()


def check_container_running(container_name: str) -> bool:
    """Check if a Docker container is running."""
    result = run_command(["docker", "ps", "--filter", f"name={container_name}", "--format", "{{.Names}}"])
    return container_name in result.stdout.strip()


def start_postgres_container() -> bool:
    """Start PostgreSQL Docker container."""
    logger.info("🔍 Checking PostgreSQL container status...")
    
    if check_container_exists(CONTAINER_NAME):
        if check_container_running(CONTAINER_NAME):
            logger.info(f"✅ Container '{CONTAINER_NAME}' is already running")
            return True
        else:
            logger.info(f"▶️  Starting existing container '{CONTAINER_NAME}'...")
            run_command(["docker", "start", CONTAINER_NAME])
            logger.info("✅ Container started")
            return True
    else:
        logger.info(f"🐳 Creating new PostgreSQL container '{CONTAINER_NAME}'...")
        run_command([
            "docker", "run", "-d",
            "--name", CONTAINER_NAME,
            "-e", f"POSTGRES_PASSWORD={POSTGRES_PASSWORD}",
            "-e", f"POSTGRES_USER={POSTGRES_USER}",
            "-p", f"{POSTGRES_PORT}:5432",
            POSTGRES_IMAGE
        ])
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
        except Exception:
            pass
        
        time.sleep(1)
        if (attempt + 1) % 5 == 0:
            logger.info(f"   Still waiting... ({attempt + 1}/{max_attempts})")
    
    logger.error("❌ PostgreSQL failed to start within the timeout period")
    return False


def download_database_backup(db_name: str, url: str, filepath: Path, force: bool = False) -> bool:
    """Download database backup file."""
    if filepath.exists() and not force:
        logger.info(f"⏭️  Backup already exists: {filepath.name}")
        return True
    
    logger.info(f"📥 Downloading {db_name} database backup from {url}...")
    try:
        import urllib.request
        urllib.request.urlretrieve(url, str(filepath))
        
        if filepath.exists() and filepath.stat().st_size > 0:
            size_mb = filepath.stat().st_size / (1024 * 1024)
            logger.info(f"✅ Downloaded: {filepath.name} ({size_mb:.2f} MB)")
            return True
        else:
            logger.error(f"❌ Download failed or file is empty: {filepath.name}")
            return False
    except Exception as e:
        logger.error(f"❌ Failed to download {db_name}: {e}")
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
        logger.info(f"⏭️  Database '{db_name}' already exists")
        return True
    
    logger.info(f"🔨 Creating database '{db_name}'...")
    try:
        run_command(
            ["createdb", "-h", "localhost", "-U", POSTGRES_USER, db_name],
            env=env
        )
        logger.info(f"✅ Database '{db_name}' created")
        return True
    except Exception as e:
        logger.error(f"❌ Failed to create database '{db_name}': {e}")
        return False


def restore_database(db_name: str, backup_file: Path) -> bool:
    """Restore database from backup file using Docker container's pg_restore."""
    if not backup_file.exists():
        logger.error(f"❌ Backup file not found: {backup_file}")
        return False
    
    logger.info(f"📦 Restoring '{db_name}' from {backup_file.name}...")
    
    try:
        # Copy backup file into container
        logger.debug(f"Copying backup file to container...")
        env = os.environ.copy()
        copy_result = run_command(
            ["docker", "cp", str(backup_file), f"{CONTAINER_NAME}:/tmp/{backup_file.name}"],
            check=False,
            env=env
        )
        
        if copy_result.returncode != 0:
            logger.error(f"❌ Failed to copy backup file to container")
            return False
        
        # Run pg_restore inside the container
        env = os.environ.copy()
        env["PGPASSWORD"] = POSTGRES_PASSWORD
        restore_result = run_command(
            ["docker", "exec", "-e", f"PGPASSWORD={POSTGRES_PASSWORD}", CONTAINER_NAME, 
             "pg_restore", "-h", "localhost", "-U", POSTGRES_USER, "-d", db_name, 
             "-v", f"/tmp/{backup_file.name}"],
            check=False,
            env=env
        )
        
        # Check if there are any tables created (check all schemas, not just public)
        env = os.environ.copy()
        env["PGPASSWORD"] = POSTGRES_PASSWORD
        count_result = run_command(
            ["psql", "-h", "localhost", "-U", POSTGRES_USER, "-d", db_name, 
             "-t", "-c", "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema NOT IN ('pg_catalog', 'information_schema');"],
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
                has_real_errors = any(err in stderr_lower for err in ['fatal', 'could not', 'failed to'])
                
                if has_real_errors:
                    logger.warning(f"⚠️  Database '{db_name}' restored with warnings ({table_count} tables created)")
                    logger.debug(f"Restore warnings: {restore_result.stderr[:500]}")
                else:
                    logger.info(f"✅ Database '{db_name}' restored successfully ({table_count} tables)")
            else:
                logger.info(f"✅ Database '{db_name}' restored successfully ({table_count} tables)")
            return True
        else:
            logger.error(f"❌ Failed to restore database '{db_name}' - no tables created")
            if restore_result.stderr:
                logger.error(f"Error details: {restore_result.stderr}")
            return False
    except Exception as e:
        logger.error(f"❌ Error restoring database '{db_name}': {e}")
        return False


def verify_database(db_name: str) -> Tuple[bool, int]:
    """Verify database has been imported correctly."""
    env = os.environ.copy()
    env["PGPASSWORD"] = POSTGRES_PASSWORD
    
    try:
        # Count tables (check all schemas, not just public)
        result = run_command(
            ["psql", "-h", "localhost", "-U", POSTGRES_USER, "-d", db_name,
             "-t", "-c", "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema NOT IN ('pg_catalog', 'information_schema');"],
            env=env
        )
        
        table_count = int(result.stdout.strip())
        
        if table_count > 0:
            logger.info(f"✅ Verified '{db_name}': {table_count} tables")
            return True, table_count
        else:
            logger.error(f"❌ Database '{db_name}' has no tables")
            return False, 0
    except Exception as e:
        logger.error(f"❌ Failed to verify database '{db_name}': {e}")
        return False, 0


def main():
    parser = argparse.ArgumentParser(description="Prepare PostgreSQL databases for MCPMark benchmarks")
    parser.add_argument("--force-download", action="store_true", help="Force re-download of database backups")
    parser.add_argument("--databases", nargs="+", choices=list(DATABASES.keys()) + ["all"], 
                        default=["all"], help="Specify which databases to prepare")
    args = parser.parse_args()
    
    # Determine which databases to prepare
    if "all" in args.databases:
        databases_to_prepare = list(DATABASES.keys())
    else:
        databases_to_prepare = args.databases
    
    logger.info("=" * 60)
    logger.info("PostgreSQL Database Preparation for MCPMark")
    logger.info("=" * 60)
    
    # Step 1: Check Docker and start container
    logger.info("\n📋 Step 1: Starting PostgreSQL Container")
    logger.info("-" * 60)
    
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
    logger.info("-" * 60)
    
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    
    download_success = {}
    for db_name in databases_to_prepare:
        db_config = DATABASES[db_name]
        filepath = DATA_DIR / db_config["filename"]
        success = download_database_backup(db_name, db_config["url"], filepath, args.force_download)
        download_success[db_name] = success
    
    if not all(download_success.values()):
        logger.error("❌ Some database backups failed to download")
        failed = [name for name, success in download_success.items() if not success]
        logger.error(f"   Failed: {', '.join(failed)}")
        return 1
    
    # Step 3: Create databases and restore
    logger.info("\n📋 Step 3: Creating Databases and Restoring from Backups")
    logger.info("-" * 60)
    
    restore_success = {}
    for db_name in databases_to_prepare:
        db_config = DATABASES[db_name]
        backup_file = DATA_DIR / db_config["filename"]
        
        # Create database
        if not create_database(db_name):
            restore_success[db_name] = False
            continue
        
        # Restore from backup
        success = restore_database(db_name, backup_file)
        restore_success[db_name] = success
    
    # Step 4: Verify databases
    logger.info("\n📋 Step 4: Verifying Database Imports")
    logger.info("-" * 60)
    
    verify_results = {}
    for db_name in databases_to_prepare:
        if restore_success.get(db_name, False):
            success, table_count = verify_database(db_name)
            verify_results[db_name] = (success, table_count)
        else:
            verify_results[db_name] = (False, 0)
    
    # Summary
    logger.info("\n" + "=" * 60)
    logger.info("📊 Summary")
    logger.info("=" * 60)
    
    all_successful = all(success for success, _ in verify_results.values())
    
    for db_name, (success, table_count) in verify_results.items():
        status = "✅" if success else "❌"
        logger.info(f"{status} {db_name:12} - {table_count:3} tables")
    
    logger.info("-" * 60)
    
    if all_successful:
        logger.info("✅ All databases prepared successfully!")
        logger.info("\n📝 PostgreSQL Configuration:")
        logger.info(f"   Host: localhost")
        logger.info(f"   Port: {POSTGRES_PORT}")
        logger.info(f"   User: {POSTGRES_USER}")
        logger.info(f"   Password: {POSTGRES_PASSWORD}")
        logger.info(f"   Databases: {', '.join(databases_to_prepare)}")
        logger.info("\n🚀 You can now run the mcpmark postgres benchmarks!")
        return 0
    else:
        logger.error("❌ Some databases failed to prepare")
        failed = [name for name, (success, _) in verify_results.items() if not success]
        logger.error(f"   Failed: {', '.join(failed)}")
        return 1


if __name__ == "__main__":
    sys.exit(main())

