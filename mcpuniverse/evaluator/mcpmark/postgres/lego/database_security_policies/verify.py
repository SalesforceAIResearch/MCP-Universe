"""
Verification script for PostgreSQL LEGO Task 4: Database Security and RLS Implementation
(Version 2 - Improved Robustness)
"""
# pylint: disable=too-many-return-statements,too-many-branches,duplicate-code

import os
import sys
from typing import Dict

import psycopg2  # type: ignore
import psycopg2.errors  # type: ignore

def get_connection_params() -> Dict[str, any]:
    """Get database connection parameters from environment variables."""
    return {
        "host": os.getenv("POSTGRES_HOST", "localhost"),
        "port": int(os.getenv("POSTGRES_PORT", "5432")),
        "database": os.getenv("POSTGRES_DATABASE"),
        "user": os.getenv("POSTGRES_USERNAME"),
        "password": os.getenv("POSTGRES_PASSWORD"),
    }

def verify_role_creation(conn) -> tuple[bool, str]:
    """
    TASK 1 VERIFICATION: Check if theme_analyst role was created with proper permissions.
    """
    print("\n-- Verifying Task 1: Role Creation and Permissions --")
    with conn.cursor() as cur:
        # Check if role exists
        cur.execute("SELECT 1 FROM pg_roles WHERE rolname = 'theme_analyst';")
        if not cur.fetchone():
            print("❌ FAIL: The 'theme_analyst' role was not created.")
            return False, "The 'theme_analyst' role was not created"
        print("✅ OK: Role 'theme_analyst' exists.")

        # Check SELECT permissions on reference and main tables
        all_tables = [
            'lego_themes', 'lego_colors', 'lego_parts', 'lego_part_categories',
            'lego_sets', 'lego_inventories', 'lego_inventory_parts'
        ]
        for table in all_tables:
            cur.execute(
                """
                SELECT has_table_privilege('theme_analyst', %s, 'SELECT');
                """,
                (table,)
            )
            if not cur.fetchone()[0]:
                print(f"❌ FAIL: 'theme_analyst' role is missing SELECT permission on '{table}'.")
                return False, f"'theme_analyst' role is missing SELECT permission on '{table}'"
        print("✅ OK: Role has correct SELECT permissions on all required tables.")

        # Check that no INSERT/UPDATE/DELETE permissions exist
        for table in all_tables:
            cur.execute(
                """
                SELECT
                    has_table_privilege('theme_analyst', %s, 'INSERT') OR
                    has_table_privilege('theme_analyst', %s, 'UPDATE') OR
                    has_table_privilege('theme_analyst', %s, 'DELETE');
                """,
                (table, table, table)
            )
            if cur.fetchone()[0]:
                print(
                    f"❌ FAIL: 'theme_analyst' role has unauthorized "
                    f"INSERT, UPDATE, or DELETE permission on '{table}'."
                )
                return False, (
                    f"'theme_analyst' role has unauthorized "
                    f"INSERT, UPDATE, or DELETE permission on '{table}'"
                )
        print("✅ OK: Role does not have modification permissions.")

        print("✅ PASS: 'theme_analyst' role created with correct permissions.")
        return True, ""

def verify_rls_enabled(conn) -> tuple[bool, str]:
    """
    TASK 2 VERIFICATION: Check if Row-Level Security is enabled on required tables.
    """
    print("\n-- Verifying Task 2: Row-Level Security Enablement --")
    tables_to_check = ['lego_sets', 'lego_inventories', 'lego_inventory_parts']
    with conn.cursor() as cur:
        for table in tables_to_check:
            cur.execute(
                "SELECT relrowsecurity FROM pg_class WHERE relname = %s;", (table,)
            )
            rls_enabled = cur.fetchone()
            if not rls_enabled or not rls_enabled[0]:
                print(f"❌ FAIL: RLS is not enabled on table '{table}'.")
                return False, f"RLS is not enabled on table '{table}'"
            print(f"✅ OK: RLS is enabled on table '{table}'.")

    print("✅ PASS: Row-Level Security is enabled on all required tables.")
    return True, ""

def verify_rls_policies(conn) -> tuple[bool, str]:
    """
    TASK 3 VERIFICATION: Check if RLS policies were created on required tables.
    """
    print("\n-- Verifying Task 3: RLS Policy Creation --")
    expected_policies = {
        'lego_sets': 'theme_sets_policy',
        'lego_inventories': 'theme_inventories_policy',
        'lego_inventory_parts': 'theme_inventory_parts_policy'
    }
    with conn.cursor() as cur:
        for table, policy_name in expected_policies.items():
            cur.execute(
                "SELECT 1 FROM pg_policies WHERE tablename = %s AND policyname = %s;",
                (table, policy_name)
            )
            if not cur.fetchone():
                print(f"❌ FAIL: RLS policy '{policy_name}' not found on table '{table}'.")
                return False, f"RLS policy '{policy_name}' not found on table '{table}'"
            print(f"✅ OK: RLS policy '{policy_name}' found on table '{table}'.")

    print("✅ PASS: All required RLS policies are created.")
    return True, ""

def verify_theme_function(conn) -> tuple[bool, str]:
    """
    TASK 4 VERIFICATION: Check if get_user_theme_id() function was created and works correctly.
    """
    print("\n-- Verifying Task 4: Theme Assignment Function --")
    with conn.cursor() as cur:
        cur.execute(
            "SELECT 1 FROM pg_proc WHERE proname = 'get_user_theme_id';"
        )
        if not cur.fetchone():
            print("❌ FAIL: The 'get_user_theme_id' function was not created.")
            return False, "The 'get_user_theme_id' function was not created"
        print("✅ OK: Function 'get_user_theme_id' exists.")

        try:
            # Test the function's output specifically for the 'theme_analyst' role
            cur.execute("SET ROLE theme_analyst;")
            cur.execute("SELECT get_user_theme_id();")
            theme_id = cur.fetchone()[0]
            cur.execute("RESET ROLE;") # IMPORTANT: Switch back

            if theme_id != 18:
                print(
                    f"❌ FAIL: get_user_theme_id() returned {theme_id} "
                    f"for 'theme_analyst', but expected 18."
                )
                return False, (
                    f"get_user_theme_id() returned {theme_id} "
                    f"for 'theme_analyst', but expected 18"
                )

            print("✅ OK: Function returns correct theme_id (18) for 'theme_analyst'.")
            print("✅ PASS: Theme assignment function is correct.")
            return True, ""
        except (psycopg2.Error, ValueError, KeyError, TypeError) as e:
            conn.rollback() # Rollback any failed transaction state
            print(f"❌ FAIL: Error testing get_user_theme_id() function: {e}")
            return False, f"Error testing get_user_theme_id() function: {e}"

def test_theme_analyst_access(conn) -> tuple[bool, str]:
    """
    TASK 5 VERIFICATION: Test data access by assuming the theme_analyst role.
    """
    print("\n-- Verifying Task 5: Theme-Based Data Access --")
    try:
        with conn.cursor() as cur:
            # Assume the role of theme_analyst for this session
            cur.execute("SET ROLE theme_analyst;")

            # Test 1: Check Star Wars sets access (should return 2 sets)
            cur.execute("SELECT set_num FROM lego_sets ORDER BY set_num;")
            star_wars_sets = [row[0] for row in cur.fetchall()]
            expected_sets = ['65081-1', 'K8008-1']

            if sorted(star_wars_sets) != sorted(expected_sets):
                print(f"❌ FAIL: Expected Star Wars sets {expected_sets}, but got {star_wars_sets}.")
                cur.execute("RESET ROLE;")
                return False, f"Expected Star Wars sets {expected_sets}, but got {star_wars_sets}"
            print("✅ PASS: Star Wars sets access is correct (2 sets returned).")

            # Test 2: Check that Technic sets are not accessible (should return 0)
            cur.execute("SELECT COUNT(*) FROM lego_sets WHERE theme_id = 1;")
            technic_count = cur.fetchone()[0]
            if technic_count != 0:
                print(
                    f"❌ FAIL: Technic sets should be blocked, but "
                    f"query returned {technic_count} sets."
                )
                cur.execute("RESET ROLE;")
                return False, (
                    f"Technic sets should be blocked, but query returned "
                    f"{technic_count} sets"
                )
            print("✅ PASS: Technic theme is correctly blocked (0 sets returned).")

            # Test 3: Check reference tables are fully accessible
            cur.execute("SELECT COUNT(*) > 10 FROM lego_themes;") # Check for a reasonable number
            if not cur.fetchone()[0]:
                print("❌ FAIL: 'lego_themes' table seems inaccessible or empty.")
                cur.execute("RESET ROLE;")
                return False, "'lego_themes' table seems inaccessible or empty"
            print("✅ PASS: Reference tables appear to be accessible.")

            # Test 4 & 5: Check related tables
            cur.execute("SELECT COUNT(*) FROM lego_inventories;")
            if cur.fetchone()[0] == 0:
                print("❌ FAIL: No inventories are visible for the allowed sets.")
                cur.execute("RESET ROLE;")
                return False, "No inventories are visible for the allowed sets"

            cur.execute("SELECT COUNT(*) FROM lego_inventory_parts;")
            if cur.fetchone()[0] == 0:
                print("❌ FAIL: No inventory parts are visible for the allowed sets.")
                cur.execute("RESET ROLE;")
                return False, "No inventory parts are visible for the allowed sets"
            print("✅ PASS: Related tables (inventories, inventory_parts) are correctly filtered.")

            # IMPORTANT: Always reset the role at the end
            cur.execute("RESET ROLE;")
            return True, ""
    except (psycopg2.Error, ValueError, KeyError, TypeError) as e:
        conn.rollback() # Ensure transaction is clean
        print(f"❌ FAIL: An error occurred while testing data access as 'theme_analyst': {e}")
        # Try to reset role even on failure to clean up session state
        try:
            with conn.cursor() as cleanup_cur:
                cleanup_cur.execute("RESET ROLE;")
        except psycopg2.Error:
            pass
        return False, f"An error occurred while testing data access as 'theme_analyst': {e}"

def verify() -> tuple[bool, str]:
    """Verification function for database security policies task."""
    print("=" * 60)
    print("LEGO Database Security and RLS Verification Script")
    print("=" * 60)

    conn_params = get_connection_params()
    if not conn_params.get("database"):
        print("❌ CRITICAL: POSTGRES_DATABASE environment variable not set.")
        return False, "POSTGRES_DATABASE environment variable not set"

    conn = None
    try:
        conn = psycopg2.connect(**conn_params)

        success, error_msg = verify_role_creation(conn)
        if not success:
            if conn:
                conn.close()
            return False, error_msg

        success, error_msg = verify_rls_enabled(conn)
        if not success:
            if conn:
                conn.close()
            return False, error_msg

        success, error_msg = verify_rls_policies(conn)
        if not success:
            if conn:
                conn.close()
            return False, error_msg

        success, error_msg = verify_theme_function(conn)
        if not success:
            if conn:
                conn.close()
            return False, error_msg

        success, error_msg = test_theme_analyst_access(conn)
        if not success:
            if conn:
                conn.close()
            return False, error_msg

        print("\n🎉 Overall Result: PASS - All security tasks verified successfully!")
        if conn:
            conn.close()
        return True, ""

    except psycopg2.OperationalError as e:
        print(
            f"❌ CRITICAL: Could not connect to the database. "
            f"Check credentials and host. Details: {e}"
        )
        if conn:
            conn.close()
        return False, f"Could not connect to the database. Details: {e}"
    except (psycopg2.Error, ValueError, KeyError, TypeError) as e:
        print(f"❌ CRITICAL: An unexpected error occurred. Details: {e}")
        if conn:
            conn.close()
        return False, f"An unexpected error occurred. Details: {e}"

def main():
    """Main verification function."""
    success, _error_msg = verify()
    if success:
        sys.exit(0)
    else:
        sys.exit(1)

if __name__ == "__main__":
    main()
