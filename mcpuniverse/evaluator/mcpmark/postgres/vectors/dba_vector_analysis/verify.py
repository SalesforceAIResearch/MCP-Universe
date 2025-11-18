"""
Verification script for Vector Database DBA Analysis task.

This script verifies that the candidate has properly analyzed the vector database
and stored their findings in appropriate result tables.
"""
# pylint: disable=too-many-return-statements,duplicate-code

import os
import sys

import psycopg2


def get_connection_params():
    """Get database connection parameters from environment variables."""
    return {
        "host": os.getenv("POSTGRES_HOST", "localhost"),
        "port": int(os.getenv("POSTGRES_PORT", "5432")),
        "database": os.getenv("POSTGRES_DATABASE"),
        "user": os.getenv("POSTGRES_USERNAME"),
        "password": os.getenv("POSTGRES_PASSWORD"),
    }


def verify_vector_analysis_columns(conn) -> tuple[bool, str]:
    """
    Verify the vector_analysis_columns table exists, has correct columns,
    and contains actual vector columns from the database.
    """
    expected_columns = [
        'schema', 'table_name', 'column_name', 'dimensions', 'data_type', 'has_constraints', 'rows'
    ]
    try:
        with conn.cursor() as cur:
            # Check if table exists
            cur.execute("""
                SELECT EXISTS (
                    SELECT FROM information_schema.tables
                    WHERE table_name = 'vector_analysis_columns'
                );
            """)
            if not cur.fetchone()[0]:
                print("vector_analysis_columns table not found")
                return False, "vector_analysis_columns table not found"

            # Check columns
            cur.execute("""
                SELECT column_name FROM information_schema.columns
                WHERE table_name = 'vector_analysis_columns'
                ORDER BY column_name;
            """)
            actual_columns = {row[0] for row in cur.fetchall()}
            missing = set(expected_columns) - actual_columns
            extra = actual_columns - set(expected_columns)
            if missing:
                print(f"Missing columns: {missing}")
                return False, f"Missing columns: {missing}"
            if extra:
                print(f"Unexpected columns: {extra}")
                return False, f"Unexpected columns: {extra}"

            # Check for data
            cur.execute("SELECT COUNT(*) FROM vector_analysis_columns;")
            count = cur.fetchone()[0]
            if count == 0:
                print("No rows found in vector_analysis_columns")
                return False, "No rows found in vector_analysis_columns"

            # Get actual vector columns from the database
            cur.execute("""
                SELECT table_name, column_name
                FROM information_schema.columns
                WHERE data_type = 'USER-DEFINED'
                AND udt_name = 'vector'
                ORDER BY table_name, column_name;
            """)
            actual_vector_columns = set(cur.fetchall())

            # Get what the agent found
            cur.execute("""
                SELECT table_name, column_name
                FROM vector_analysis_columns
                ORDER BY table_name, column_name;
            """)
            found_vector_columns = set(cur.fetchall())

            # Check if agent found the actual vector columns
            missing_vectors = actual_vector_columns - found_vector_columns
            extra_vectors = found_vector_columns - actual_vector_columns

            if missing_vectors:
                print(f"Missing: {missing_vectors}")
                return False, f"Missing: {missing_vectors}"
            if extra_vectors:
                print(f"Non-existing: {extra_vectors}")
                return False, f"Non-existing: {extra_vectors}"

            return True, ""

    except psycopg2.Error as e:
        print(f"Database error: {e}")
        return False, f"Database error: {e}"
    except (ValueError, KeyError, TypeError) as e:
        print(f"Verification error: {e}")
        return False, f"Verification error: {e}"


def verify_vector_analysis_storage_consumption(conn) -> tuple[bool, str]:
    """
    Verify the vector_analysis_storage_consumption table exists,
    has correct columns, and analyzes actual vector tables.
    """
    expected_columns = [
        'schema', 'table_name', 'total_size_bytes', 'vector_data_bytes',
        'regular_data_bytes', 'vector_storage_pct', 'row_count'
    ]
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT EXISTS (
                    SELECT FROM information_schema.tables
                    WHERE table_name = 'vector_analysis_storage_consumption'
                );
            """)
            if not cur.fetchone()[0]:
                print("vector_analysis_storage_consumption table not found")
                return False, "vector_analysis_storage_consumption table not found"

            cur.execute("""
                SELECT column_name FROM information_schema.columns
                WHERE table_name = 'vector_analysis_storage_consumption'
                ORDER BY column_name;
            """)
            actual_columns = {row[0] for row in cur.fetchall()}
            missing = set(expected_columns) - actual_columns
            extra = actual_columns - set(expected_columns)
            if missing:
                print(f"Missing columns: {missing}")
                return False, f"Missing columns: {missing}"
            if extra:
                print(f"Unexpected columns: {extra}")
                return False, f"Unexpected columns: {extra}"

            cur.execute("SELECT COUNT(*) FROM vector_analysis_storage_consumption;")
            count = cur.fetchone()[0]
            if count == 0:
                print("No rows found in vector_analysis_storage_consumption")
                return False, "No rows found in vector_analysis_storage_consumption"

            # Get actual tables with vector columns
            cur.execute("""
                SELECT DISTINCT table_name
                FROM information_schema.columns
                WHERE data_type = 'USER-DEFINED'
                AND udt_name = 'vector'
                ORDER BY table_name;
            """)
            actual_vector_tables = {row[0] for row in cur.fetchall()}

            # Get what the agent analyzed
            cur.execute("""
                SELECT DISTINCT table_name
                FROM vector_analysis_storage_consumption
                ORDER BY table_name;
            """)
            analyzed_tables = {row[0] for row in cur.fetchall()}

            # Check if agent analyzed the actual vector tables
            missing_tables = actual_vector_tables - analyzed_tables
            if missing_tables:
                print(f"Agent missed analyzing vector tables: {missing_tables}")
                return False, f"Agent missed analyzing vector tables: {missing_tables}"

            # Check that analyzed tables actually have vector columns
            extra_tables = analyzed_tables - actual_vector_tables
            if extra_tables:
                print(f"Agent analyzed non-vector tables: {extra_tables}")
                return False, f"Agent analyzed non-vector tables: {extra_tables}"

            return True, ""

    except psycopg2.Error as e:
        print(f"Database error: {e}")
        return False, f"Database error: {e}"
    except (ValueError, KeyError, TypeError) as e:
        print(f"Verification error: {e}")
        return False, f"Verification error: {e}"


def verify_vector_analysis_indices(conn) -> tuple[bool, str]:
    """
    Verify the vector_analysis_indices table exists, has correct columns,
    and identifies actual vector indexes.
    """
    expected_columns = [
        'schema', 'table_name', 'column_name', 'index_name', 'index_type', 'index_size_bytes'
    ]
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT EXISTS (
                    SELECT FROM information_schema.tables
                    WHERE table_name = 'vector_analysis_indices'
                );
            """)
            if not cur.fetchone()[0]:
                print("vector_analysis_indices table not found")
                return False, "vector_analysis_indices table not found"

            cur.execute("""
                SELECT column_name FROM information_schema.columns
                WHERE table_name = 'vector_analysis_indices'
                ORDER BY column_name;
            """)
            actual_columns = {row[0] for row in cur.fetchall()}
            missing = set(expected_columns) - actual_columns
            extra = actual_columns - set(expected_columns)
            if missing:
                print(f"Missing columns: {missing}")
                return False, f"Missing columns: {missing}"
            if extra:
                print(f"Unexpected columns: {extra}")
                return False, f"Unexpected columns: {extra}"

            cur.execute("SELECT COUNT(*) FROM vector_analysis_indices;")
            count = cur.fetchone()[0]
            if count == 0:
                print("No rows found in vector_analysis_indices")
                return False, "No rows found in vector_analysis_indices"

            # Get actual vector indexes from the database (exclude ground truth table indexes)
            cur.execute("""
                SELECT schemaname, tablename, indexname
                FROM pg_indexes
                WHERE (indexdef ILIKE '%hnsw%' OR indexdef ILIKE '%ivfflat%')
                AND tablename NOT LIKE '%analysis%'
                ORDER BY tablename, indexname;
            """)
            actual_vector_indexes = set(cur.fetchall())

            # Get what the agent found
            cur.execute("""
                SELECT schema, table_name, index_name
                FROM vector_analysis_indices
                ORDER BY table_name, index_name;
            """)
            found_indexes = set(cur.fetchall())

            # Check if agent found the actual vector indexes
            missing_indexes = actual_vector_indexes - found_indexes
            if missing_indexes:
                print(f"Agent missed vector indexes: {missing_indexes}")
                return False, f"Agent missed vector indexes: {missing_indexes}"

            # Allow agent to find more indexes than just vector ones
            # (they might include related indexes)
            # but at least they should find the vector-specific ones

            return True, ""

    except psycopg2.Error as e:
        print(f"Database error: {e}")
        return False, f"Database error: {e}"
    except (ValueError, KeyError, TypeError) as e:
        print(f"Verification error: {e}")
        return False, f"Verification error: {e}"


def verify_no_extra_analysis_tables(conn) -> tuple[bool, str]:
    """Check that only the required analysis tables exist (no legacy/extra analysis tables)."""
    required = {
        'vector_analysis_columns',
        'vector_analysis_storage_consumption',
        'vector_analysis_indices',
    }
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT table_name FROM information_schema.tables
                WHERE table_schema = 'public'
                AND table_name LIKE 'vector_analysis_%';
            """)
            analysis_tables = {row[0] for row in cur.fetchall()}

            # Only flag as issue if there are analysis tables that don't
            # match our required set. Exclude ground truth tables from this
            # check
            analysis_tables_filtered = {
                t for t in analysis_tables
                if not t.startswith('expected_')
                and not t.startswith('vector_analysis_results')
            }
            extra = analysis_tables_filtered - required
            if extra:
                print(f"Found unexpected analysis tables: {extra}")
                return False, f"Found unexpected analysis tables: {extra}"

            return True, ""

    except (psycopg2.Error, ValueError, KeyError, TypeError) as e:
        print(f"Verification error: {e}")
        return False, f"Verification error: {e}"



def verify() -> tuple[bool, str]:
    """Verification function for vector database analysis task."""
    conn_params = get_connection_params()
    if not conn_params["database"]:
        print("No database specified")
        return False, "No database specified"

    try:
        conn = psycopg2.connect(**conn_params)

        # Run all verification checks
        success, error_msg = verify_vector_analysis_columns(conn)
        if not success:
            conn.close()
            return False, error_msg
        print("  PASSED: vector_analysis_columns")

        success, error_msg = verify_vector_analysis_storage_consumption(conn)
        if not success:
            conn.close()
            return False, error_msg
        print("  PASSED: vector_analysis_storage_consumption")

        success, error_msg = verify_vector_analysis_indices(conn)
        if not success:
            conn.close()
            return False, error_msg
        print("  PASSED: vector_analysis_indices")

        success, error_msg = verify_no_extra_analysis_tables(conn)
        if not success:
            conn.close()
            return False, error_msg
        print("  PASSED: no_extra_analysis_tables")

        conn.close()
        print("\nResults: 4/4 checks passed")
        return True, ""

    except psycopg2.Error as e:
        print(f"Database connection error: {e}")
        return False, f"Database connection error: {e}"
    except (ValueError, KeyError, TypeError) as e:
        print(f"Verification error: {e}")
        return False, f"Verification error: {e}"

def main():
    """Main verification function for vector analysis deliverables."""
    success, _error_msg = verify()
    if success:
        sys.exit(0)
    else:
        sys.exit(1)


if __name__ == "__main__":
    main()
