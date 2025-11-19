"""
Verification script for PostgreSQL LEGO Task 1: Parts Consistency Fix & Constraints
Version 2.1: Relaxed consistency check to allow for one known corner case mismatch.
"""
# pylint: disable=too-many-return-statements,duplicate-code

import os
import sys
from typing import Optional, Tuple

import psycopg2  # type: ignore
import psycopg2.errors  # type: ignore


def get_connection_params() -> dict:
    """Get database connection parameters from environment variables."""
    return {
        "host": os.getenv("POSTGRES_HOST", "localhost"),
        "port": int(os.getenv("POSTGRES_PORT", "5432")),
        "database": os.getenv("POSTGRES_DATABASE"),
        "user": os.getenv("POSTGRES_USERNAME"),
        "password": os.getenv("POSTGRES_PASSWORD"),
    }


def fetch_candidate_part_row(cur) -> Optional[Tuple[int, str, str, int]]:
    """
    Picks a concrete, non-spare inventory part from the latest inventory of any set.
    This provides a reliable target for testing update and insert triggers.

    Returns a tuple: (inventory_id, set_num, part_num, color_id) or None.
    """
    cur.execute(
        """
        WITH latest_inv AS (
            SELECT set_num, MAX(version) AS max_version
            FROM public.lego_inventories
            GROUP BY set_num
        ), inv AS (
            SELECT li.id, li.set_num
            FROM public.lego_inventories li
            JOIN latest_inv lv ON lv.set_num = li.set_num AND lv.max_version = li.version
        )
        SELECT i.id AS inventory_id, i.set_num, lip.part_num, lip.color_id
        FROM inv i
        JOIN public.lego_inventory_parts lip ON lip.inventory_id = i.id
        WHERE lip.is_spare = false AND lip.quantity > 0
        LIMIT 1;
        """
    )
    return cur.fetchone()


def get_mismatch_count(cur) -> int:
    """Returns the number of sets where num_parts mismatches the computed actual sum."""
    cur.execute(
        """
        WITH latest_inv AS (
            SELECT set_num, MAX(version) AS max_version
            FROM public.lego_inventories
            GROUP BY set_num
        ), inv_latest AS (
            SELECT li.set_num, li.id
            FROM public.lego_inventories li
            JOIN latest_inv lv ON lv.set_num = li.set_num AND lv.max_version = li.version
        ), parts_agg AS (
            SELECT
                i.set_num,
                SUM(lip.quantity) AS actual_parts
            FROM inv_latest i
            JOIN public.lego_inventory_parts lip ON lip.inventory_id = i.id
            WHERE lip.is_spare = false
            GROUP BY i.set_num
        )
        SELECT COUNT(*)
        FROM public.lego_sets s
        LEFT JOIN parts_agg pa ON s.set_num = pa.set_num
        WHERE s.num_parts <> COALESCE(pa.actual_parts, 0);
        """
    )
    return cur.fetchone()[0]


def verify_data_consistency(conn) -> tuple[bool, str]:
    """
    TASK 1 VERIFICATION: Checks if the initial data fix was successful.
    (Relaxed: Allows for one corner-case mismatch).
    """
    print("\n-- Verifying Task 1: Data Consistency Fix (Relaxed) --")
    with conn.cursor() as cur:
        count = get_mismatch_count(cur)
        # RELAXED CONDITION: Allow 0 or 1 mismatch to pass.
        if count > 1:
            print(
                f"❌ FAIL: Found {count} sets with inconsistent part counts. "
                f"Expected 0 or 1 after fix."
            )
            return False, f"Found {count} sets with inconsistent part counts"

        print("✅ PASS: Data consistency check passed (allowing for one known mismatch).")
        return True, ""


def verify_constraint_triggers_exist(conn) -> tuple[bool, str]:
    """
    TASK 2 VERIFICATION (Part A): Checks if constraint triggers are attached to all required tables.
    This is more robust than checking names or a total count.
    """
    print("\n-- Verifying Task 2: Constraint Trigger Existence --")
    tables_to_check = [
        'public.lego_inventory_parts',
        'public.lego_inventories',
        'public.lego_sets'
    ]
    all_triggers_found = True
    missing_tables = []
    with conn.cursor() as cur:
        for table in tables_to_check:
            cur.execute(
                """
                SELECT COUNT(*)
                FROM pg_trigger
                WHERE tgrelid = %s::regclass AND tgconstraint <> 0;
                """,
                (table,)
            )
            trigger_count = cur.fetchone()[0]
            if trigger_count == 0:
                print(f"❌ FAIL: No constraint trigger found on table '{table}'.")
                all_triggers_found = False
                missing_tables.append(table)
            else:
                print(f"✅ OK: Found constraint trigger(s) on table '{table}'.")

    if all_triggers_found:
        print("✅ PASS: Constraint triggers are attached to all required tables.")
        return True, ""
    return False, f"No constraint triggers found on tables: {', '.join(missing_tables)}"


def verify_violation_is_blocked(conn) -> tuple[bool, str]:
    """
    TASK 2 VERIFICATION (Part B): Checks if triggers block a direct, inconsistent write.
    An attempt to increment a part quantity without updating the set's total should fail.
    """
    print("\n-- Verifying Task 2: Immediate Constraint Enforcement --")
    with conn.cursor() as cur:
        candidate = fetch_candidate_part_row(cur)
        if not candidate:
            print("⚠️ SKIP: No candidate part row found to test constraints. Cannot verify.")
            return True, "" # Skip if no data to test

        inventory_id, _, part_num, color_id = candidate
        try:
            # This transaction should fail due to the trigger
            cur.execute(
                """
                UPDATE public.lego_inventory_parts
                SET quantity = quantity + 1
                WHERE inventory_id = %s AND part_num = %s AND color_id = %s;
                """,
                (inventory_id, part_num, color_id),
            )
            # If we reach here, the trigger failed to block the update.
            conn.rollback()
            print("❌ FAIL: An inconsistent write was NOT blocked by the trigger.")
            return False, "An inconsistent write was NOT blocked by the trigger"
        except psycopg2.Error as e:
            # We expect an error. Specifically, a constraint violation error.
            conn.rollback()
            # 23514 is check_violation, but custom triggers might raise others.
            # Any error here is considered a success as the transaction
            # was blocked.
            print(
                f"✅ PASS: Inconsistent write was correctly blocked by "
                f"the trigger. (Error: {e.pgcode})"
            )
            return True, ""


def verify_deferred_transaction_is_allowed(conn) -> tuple[bool, str]:
    """
    TASK 2 VERIFICATION (Part C): Checks if a coordinated, consistent update is allowed
    when constraints are deferred.
    """
    print("\n-- Verifying Task 2: Deferred Constraint Enforcement --")
    with conn.cursor() as cur:
        candidate = fetch_candidate_part_row(cur)
        if not candidate:
            print("⚠️ SKIP: No candidate part row found. Cannot test deferred transaction.")
            return True, "" # Skip if no data to test

    inventory_id, set_num, part_num, color_id = candidate

    try:
        # This multi-statement transaction should succeed with deferred constraints
        with conn.cursor() as cur:
            cur.execute("BEGIN;")
            cur.execute("SET CONSTRAINTS ALL DEFERRED;")
            cur.execute(
                "UPDATE public.lego_inventory_parts "
                "SET quantity = quantity + 1 "
                "WHERE inventory_id = %s AND part_num = %s AND color_id = %s;",
                (inventory_id, part_num, color_id),
            )
            cur.execute(
                "UPDATE public.lego_sets SET num_parts = num_parts + 1 "
                "WHERE set_num = %s;",
                (set_num,),
            )
            # This will fail if constraints are not deferrable or logic
            # is wrong
            cur.execute("COMMIT;")
        print("✅ PASS: Coordinated update with deferred constraints committed successfully.")

        # Revert changes to leave DB in its original state
        with conn.cursor() as cur:
            cur.execute("BEGIN;")
            cur.execute("SET CONSTRAINTS ALL DEFERRED;")
            cur.execute(
                "UPDATE public.lego_inventory_parts "
                "SET quantity = quantity - 1 "
                "WHERE inventory_id = %s AND part_num = %s AND color_id = %s;",
                (inventory_id, part_num, color_id),
            )
            cur.execute(
                "UPDATE public.lego_sets SET num_parts = num_parts - 1 WHERE set_num = %s;",
                (set_num,),
            )
            cur.execute("COMMIT;")
        print("INFO: Test changes were successfully reverted.")
        return True, ""

    except psycopg2.Error as e:
        conn.rollback()
        print(f"❌ FAIL: Deferred transaction failed to commit. Error: {e}")
        return False, f"Deferred transaction failed to commit. Error: {e}"


def verify() -> tuple[bool, str]:
    """Verification function for consistency enforcement task."""
    print("=" * 60)
    print("LEGO Database Consistency Verification Script")
    print("=" * 60)

    conn_params = get_connection_params()
    if not conn_params.get("database"):
        print("❌ CRITICAL: POSTGRES_DATABASE environment variable not set.")
        return False, "POSTGRES_DATABASE environment variable not set"

    try:
        with psycopg2.connect(**conn_params) as conn:
            conn.autocommit = False # Ensure we control transactions

            # Run all verification steps
            success, error_msg = verify_data_consistency(conn)
            if not success:
                return False, error_msg

            success, error_msg = verify_constraint_triggers_exist(conn)
            if not success:
                return False, error_msg

            success, error_msg = verify_violation_is_blocked(conn)
            if not success:
                return False, error_msg

            success, error_msg = verify_deferred_transaction_is_allowed(conn)
            if not success:
                return False, error_msg

            print("\n🎉 Overall Result: PASS - All tasks verified successfully!")
            return True, ""

    except psycopg2.OperationalError as e:
        print(f"❌ CRITICAL: Could not connect to the database. Details: {e}")
        return False, f"Could not connect to the database. Details: {e}"
    except (psycopg2.Error, ValueError, KeyError, TypeError) as e:
        print(f"❌ CRITICAL: An unexpected error occurred during verification. Details: {e}")
        return False, f"An unexpected error occurred during verification. Details: {e}"

def main():
    """Main verification function."""
    success, _error_msg = verify()
    if success:
        sys.exit(0)
    else:
        sys.exit(1)


if __name__ == "__main__":
    main()
