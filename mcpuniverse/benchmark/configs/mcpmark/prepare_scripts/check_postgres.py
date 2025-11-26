#!/usr/bin/env python3
"""
Quick PostgreSQL Status Check Script
=====================================

This script quickly checks the status of PostgreSQL setup for MCPMark benchmarks.

Usage:
    python check_postgres.py
"""

import subprocess
import sys
import os

CONTAINER_NAME = "mcpmark-postgres"
POSTGRES_USER = "postgres"
POSTGRES_PASSWORD = "password"
DATABASES = ["chinook", "employees", "dvdrental", "sports"]


def run_command(cmd, check=False, capture_output=True):
    """Run a shell command."""
    try:
        return subprocess.run(cmd, check=check, capture_output=capture_output, text=True)
    except (OSError, subprocess.SubprocessError):
        return None


def check_docker():
    """Check if Docker is running."""
    result = run_command(["docker", "ps"])
    return result and result.returncode == 0


def check_container_running():
    """Check if PostgreSQL container is running."""
    result = run_command([
        "docker",
        "ps",
        "--filter",
        f"name={CONTAINER_NAME}",
        "--format",
        "{{.Names}}",
    ])
    return result and CONTAINER_NAME in result.stdout


def check_database(db_name):
    """Check if database exists and has tables."""
    env = os.environ.copy()
    env["PGPASSWORD"] = POSTGRES_PASSWORD

    # Check if database exists
    result = subprocess.run(
        ["psql", "-h", "localhost", "-U", POSTGRES_USER, "-lqt"],
        check=False,
        capture_output=True,
        text=True,
        env=env
    )

    if not result or db_name not in result.stdout:
        return False, 0

    # Count tables (check all schemas, not just public)
    sql = (
        "SELECT COUNT(*) FROM information_schema.tables "
        "WHERE table_schema NOT IN ('pg_catalog', 'information_schema');"
    )
    result = subprocess.run(
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
            sql,
        ],
        check=False,
        capture_output=True,
        text=True,
        env=env
    )

    if result and result.returncode == 0:
        try:
            table_count = int(result.stdout.strip())
            return True, table_count
        except ValueError:
            return False, 0

    return False, 0


def main():
    """Entry point to check Docker, container, and database readiness."""
    print("🔍 PostgreSQL Setup Status Check")
    print("=" * 60)
    print()

    # Check Docker
    print("📦 Docker Status:")
    if check_docker():
        print("   ✅ Docker is running")
    else:
        print("   ❌ Docker is not running")
        print("\n💡 Please start Docker and run setup:")
        print("   ./mcpmark/prepare_scripts/setup_postgres.sh")
        return 1

    # Check Container
    print("\n🐳 PostgreSQL Container:")
    if check_container_running():
        print(f"   ✅ Container '{CONTAINER_NAME}' is running")
    else:
        print(f"   ❌ Container '{CONTAINER_NAME}' is not running")
        print("\n💡 Run setup to start the container:")
        print("   ./mcpmark/prepare_scripts/setup_postgres.sh")
        return 1

    # Check Databases
    print("\n💾 Database Status:")
    all_ok = True
    db_status = {}

    for db_name in DATABASES:
        exists, table_count = check_database(db_name)
        db_status[db_name] = (exists, table_count)

        if exists:
            print(f"   ✅ {db_name:12} - {table_count:3} tables")
        else:
            print(f"   ❌ {db_name:12} - Not found or empty")
            all_ok = False

    print("\n" + "=" * 60)

    if all_ok:
        print("✅ PostgreSQL is ready for benchmarks!")
        print("\n🚀 You can now run:")
        print("   python tests/benchmark/test_benchmark_mcpmark_postgres.py")
        return 0
    print("❌ Some databases are not ready")
    print("\n💡 Run setup to prepare all databases:")
    print("   ./mcpmark/prepare_scripts/setup_postgres.sh")
    return 1


if __name__ == "__main__":
    sys.exit(main())
