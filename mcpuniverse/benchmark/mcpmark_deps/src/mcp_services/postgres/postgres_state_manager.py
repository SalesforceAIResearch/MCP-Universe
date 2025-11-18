"""
PostgreSQL State Manager for MCPMark
=====================================

Manages database state for PostgreSQL tasks including schema setup,
test data creation, and cleanup.
"""
# pylint: disable=import-error
import os
import subprocess
import sys
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import psycopg2
from psycopg2 import sql

from src.base.state_manager import BaseStateManager, InitialStateInfo
from src.base.task_manager import BaseTask
from src.logger import get_logger

logger = get_logger(__name__)


class PostgresStateManager(BaseStateManager):  # pylint: disable=too-many-instance-attributes, too-few-public-methods
    """Manages PostgreSQL database state for task evaluation."""

    def __init__(  # pylint: disable=too-many-arguments, too-many-positional-arguments
        self,
        host: str = "localhost",
        port: int = 5432,
        database: str = "postgres",
        username: str = "postgres",
        password: str = None,
    ):
        """Initialize PostgreSQL state manager.

        Args:
            host: Database host
            port: Database port
            database: Main database name
            username: Database username
            password: Database password
            template_db: Template database for initial states
        """
        super().__init__(service_name="postgres")

        self.host = host
        self.port = port
        self.database = database
        self.username = username
        self.password = password

        # Connection parameters
        self.conn_params = {
            "host": host,
            "port": port,
            "user": username,
            "password": password,
        }

        # Track created databases for cleanup
        self.created_databases: List[str] = []

        # Track current task database for agent configuration
        self._current_task_database: Optional[str] = None

        # Validate connection on initialization
        try:
            self._test_connection()
            logger.info("PostgreSQL state manager initialized successfully")
            self._setup_database()
        except Exception as exc:
            raise RuntimeError(
                f"PostgreSQL initialization failed: {exc}"
            ) from exc

    def _test_connection(self):
        """Test database connection."""
        conn = psycopg2.connect(**self.conn_params, database="postgres")
        conn.close()

    def _setup_database(self):
        """Setup all required databases by downloading and restoring from backup."""
        databases = ['employees', 'chinook', 'dvdrental', 'sports', 'lego']

        for db_name in databases:
            if not self._database_exists(db_name):
                logger.info("Setting up %s database...", db_name)

                # Path to backup file in MCP-Universe/tests/data/postgres
                # Navigate from mcpmark_deps/src/mcp_services/postgres to MCP-Universe root
                # Path: mcpmark_deps/src/mcp_services/postgres -> benchmark -> mcpuniverse
                # -> MCP-Universe
                mcpuniverse_root = (
                    Path(__file__).parent.parent.parent.parent.parent.parent.parent
                )
                backup_dir = mcpuniverse_root / "tests" / "data" / "postgres"
                backup_file = backup_dir / f"{db_name}.backup"

                # Download backup if not exists
                if not backup_file.exists():
                    backup_dir.mkdir(parents=True, exist_ok=True)
                    logger.info("Downloading %s backup...", db_name)
                    try:
                        urllib.request.urlretrieve(
                            f'https://storage.mcpmark.ai/postgres/{db_name}.backup',
                            str(backup_file)
                        )
                        logger.info("%s backup downloaded", db_name)
                    except Exception as exc:  # pylint: disable=broad-exception-caught
                        logger.warning("Failed to download %s backup: %s", db_name, exc)
                        continue

                # Create database
                try:
                    self._create_empty_database(db_name)
                    logger.info("Created %s database", db_name)
                except Exception as exc:  # pylint: disable=broad-exception-caught
                    logger.warning("Failed to create %s database: %s", db_name, exc)
                    continue

                # Restore from backup
                env = os.environ.copy()
                env['PGPASSWORD'] = self.password

                try:
                    result = subprocess.run([
                        'pg_restore',
                        '-h', str(self.host),
                        '-p', str(self.port),
                        '-U', self.username,
                        '-d', db_name,
                        '-v',
                        str(backup_file)
                    ], env=env, capture_output=True, text=True, check=False)

                    if result.returncode != 0 and "ERROR" in result.stderr:
                        logger.warning(
                            "pg_restore had errors for %s: %s",
                            db_name,
                            result.stderr
                        )
                    else:
                        logger.info("%s database restored successfully", db_name)
                except Exception as exc:  # pylint: disable=broad-exception-caught
                    logger.warning("Failed to restore %s database: %s", db_name, exc)
            else:
                logger.debug("%s database already exists", db_name)

    def _create_initial_state(self, task: BaseTask) -> Optional[InitialStateInfo]:
        """Create initial database state for a task."""
        try:
            # Generate unique database name
            db_name = f"mcpmark_{task.category_id}_{task.task_id}_{self._get_timestamp()}"

            # Create database from template if exists, otherwise empty
            if self._database_exists(task.category_id):
                self._create_database_from_template(db_name, task.category_id)
                logger.info(
                    "| Created database '%s' from template '%s'",
                    db_name,
                    task.category_id
                )
            else:
                self._create_empty_database(db_name)
                logger.info("| Created empty database '%s'", db_name)
                # Run prepare_environment.py if it exists
                self._run_prepare_environment(db_name, task)
                logger.info("| Prepared environment for database '%s'", db_name)

            # Track for cleanup
            self.created_databases.append(db_name)
            self.track_resource("database", db_name, {"task": task.name})


            return InitialStateInfo(
                state_id=db_name,
                state_url=f"postgresql://{self.username}@{self.host}:{self.port}/{db_name}",
                metadata={
                    "database": db_name,
                    "category": task.category_id,
                    "task_id": task.task_id,
                },
            )

        except Exception as exc:  # pylint: disable=broad-exception-caught
            logger.error("Failed to create initial state for %s: %s", task.name, exc)
            return None

    def _store_initial_state_info(
        self, task: BaseTask, state_info: InitialStateInfo
    ) -> None:
        """Store database info in task object."""
        if hasattr(task, "__dict__"):
            task.database_name = state_info.state_id
            task.database_url = state_info.state_url
            # Store current task database for agent configuration
            self._current_task_database = state_info.state_id

    def _cleanup_task_initial_state(self, task: BaseTask) -> bool:
        """Clean up task database."""
        if hasattr(task, "database_name") and task.database_name:
            try:
                self._drop_database(task.database_name)
                logger.info("| Dropped database: %s", task.database_name)

                # Remove from tracking
                self.created_databases = [
                    db for db in self.created_databases if db != task.database_name
                ]
                # Clear current task database
                if self._current_task_database == task.database_name:
                    self._current_task_database = None
                return True
            except Exception as exc:  # pylint: disable=broad-exception-caught
                logger.error(
                    "Failed to drop database %s: %s",
                    task.database_name,
                    exc
                )
                return False
        return True

    def _cleanup_single_resource(self, resource: Dict[str, Any]) -> bool:
        """Clean up a single PostgreSQL resource."""
        if resource["type"] == "database":
            try:
                self._drop_database(resource["id"])
                logger.info("| Dropped database: %s", resource['id'])
                return True
            except Exception as exc:  # pylint: disable=broad-exception-caught
                logger.error("| Failed to drop database %s: %s", resource['id'], exc)
                return False
        return False

    def _database_exists(self, db_name: str) -> bool:
        """Check if database exists."""
        conn = psycopg2.connect(**self.conn_params, database="postgres")
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT 1 FROM pg_database WHERE datname = %s", (db_name,))
                return cur.fetchone() is not None
        finally:
            conn.close()

    def _create_database_from_template(self, new_db: str, template_db: str):
        """Create database from template."""
        conn = psycopg2.connect(**self.conn_params, database="postgres")
        conn.autocommit = True
        try:
            with conn.cursor() as cur:
                cur.execute(
                    sql.SQL("""
                    SELECT pg_terminate_backend(pid)
                    FROM pg_stat_activity
                    WHERE datname = %s AND pid <> pg_backend_pid()
                """),
                    (template_db,),
                )
                cur.execute(
                    sql.SQL("CREATE DATABASE {} WITH TEMPLATE {}").format(
                        sql.Identifier(new_db), sql.Identifier(template_db)
                    )
                )
        finally:
            conn.close()

    def _create_empty_database(self, db_name: str):
        """Create empty database."""
        conn = psycopg2.connect(**self.conn_params, database="postgres")
        conn.autocommit = True
        try:
            with conn.cursor() as cur:
                cur.execute(
                    sql.SQL("CREATE DATABASE {}").format(sql.Identifier(db_name))
                )
        finally:
            conn.close()

    def _drop_database(self, db_name: str):
        """Drop database."""
        conn = psycopg2.connect(**self.conn_params, database="postgres")
        conn.autocommit = True
        try:
            with conn.cursor() as cur:
                # Terminate connections
                cur.execute(
                    sql.SQL("""
                    SELECT pg_terminate_backend(pid)
                    FROM pg_stat_activity
                    WHERE datname = %s AND pid <> pg_backend_pid()
                """),
                    (db_name,),
                )

                # Drop database
                cur.execute(
                    sql.SQL("DROP DATABASE IF EXISTS {}").format(
                        sql.Identifier(db_name)
                    )
                )
        finally:
            conn.close()

    def _run_prepare_environment(self, db_name: str, task: BaseTask):
        """Run prepare_environment.py script if it exists in the task directory."""
        # Find the task directory containing prepare_environment.py
        task_dir = task.task_instruction_path.parent
        prepare_script = task_dir / "prepare_environment.py"

        if not prepare_script.exists():
            logger.debug("No prepare_environment.py found for task %s", task.name)
            return

        logger.info("| Running prepare_environment.py for task %s", task.name)

        # Set up environment variables for the script
        env = os.environ.copy()
        env.update({
            "POSTGRES_HOST": str(self.host),
            "POSTGRES_PORT": str(self.port),
            "POSTGRES_DATABASE": db_name,
            "POSTGRES_USERNAME": self.username,
            "POSTGRES_PASSWORD": self.password or "",
        })

        try:
            # Run the prepare_environment.py script
            result = subprocess.run(
                [sys.executable, str(prepare_script)],
                cwd=str(task_dir),  # Run from task directory to access data/ folder
                check=False,
                env=env,
                capture_output=True,
                text=True,
                timeout=300,  # 5 minute timeout
            )

            if result.returncode == 0:
                logger.info(
                    "| ✓ Environment preparation completed for %s",
                    task.name
                )
                if result.stdout.strip():
                    logger.debug("| prepare_environment.py output: %s", result.stdout)
            else:
                logger.error(
                    "| ❌ Environment preparation failed for %s",
                    task.name
                )
                logger.error("| Error output: %s", result.stderr)
                raise RuntimeError(
                    f"prepare_environment.py failed with exit code "
                    f"{result.returncode}"
                )

        except subprocess.TimeoutExpired as exc:
            logger.error("❌ Environment preparation timed out for %s", task.name)
            raise RuntimeError("prepare_environment.py execution timed out") from exc
        except Exception as exc:  # pylint: disable=broad-exception-caught
            logger.error(
                "❌ Failed to run prepare_environment.py for %s: %s",
                task.name,
                exc
            )
            raise

    def _setup_task_specific_data(self, db_name: str, task: BaseTask):
        """Set up task-specific schema and data."""
        conn = psycopg2.connect(**self.conn_params, database=db_name)
        try:
            with conn.cursor() as cur:
                if task.category_id == "basic_queries":
                    self._setup_basic_queries_data(cur)
                elif task.category_id == "data_manipulation":
                    self._setup_data_manipulation_data(cur)
                elif task.category_id == "table_operations":
                    self._setup_table_operations_data(cur)
                # Add more categories as needed

            conn.commit()
        except Exception as exc:  # pylint: disable=broad-exception-caught
            conn.rollback()
            logger.error("Failed to setup task data: %s", exc)
            raise
        finally:
            conn.close()

    def _setup_basic_queries_data(self, cursor):
        """Set up data for basic query tasks."""
        cursor.execute("""
            CREATE TABLE employees (
                id SERIAL PRIMARY KEY,
                name VARCHAR(100) NOT NULL,
                department VARCHAR(50),
                salary DECIMAL(10, 2),
                hire_date DATE
            );

            INSERT INTO employees (name, department, salary, hire_date) VALUES
            ('John Doe', 'Engineering', 75000.00, '2020-01-15'),
            ('Jane Smith', 'Marketing', 65000.00, '2019-03-22'),
            ('Bob Johnson', 'Engineering', 80000.00, '2018-07-01'),
            ('Alice Brown', 'HR', 55000.00, '2021-02-10');
        """)

    def _setup_data_manipulation_data(self, cursor):
        """Set up data for data manipulation tasks."""
        cursor.execute("""
            CREATE TABLE products (
                id SERIAL PRIMARY KEY,
                name VARCHAR(100) NOT NULL,
                category VARCHAR(50),
                price DECIMAL(10, 2),
                stock INTEGER DEFAULT 0
            );

            CREATE TABLE orders (
                id SERIAL PRIMARY KEY,
                product_id INTEGER REFERENCES products(id),
                quantity INTEGER NOT NULL,
                order_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)

    def _setup_table_operations_data(self, cursor):
        """Set up for table operation tasks."""
        # Start with minimal schema that tasks will modify
        cursor.execute("""
            CREATE TABLE test_table (
                id SERIAL PRIMARY KEY,
                data VARCHAR(255)
            );
        """)

    def _get_timestamp(self) -> str:
        """Get timestamp for unique naming."""
        return datetime.now().strftime("%Y%m%d%H%M%S")

    def get_service_config_for_agent(self) -> dict:
        """Get configuration for agent execution."""
        config = {
            "host": self.host,
            "port": self.port,
            "username": self.username,
            "password": self.password,
        }

        # If there's a current task database, include it
        if hasattr(self, "_current_task_database") and self._current_task_database:
            config["current_database"] = self._current_task_database
            config["database_url"] = (
                f"postgresql://{self.username}:{self.password}@{self.host}:"
                f"{self.port}/{self._current_task_database}"
            )
        else:
            # Fallback to default database
            config["database"] = self.database
            config["database_url"] = (
                f"postgresql://{self.username}:{self.password}@{self.host}:"
                f"{self.port}/{self.database}"
            )

        return config
