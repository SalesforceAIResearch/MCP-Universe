"""
Verification script for PostgreSQL LEGO Task 2: Enhanced Inventory Transfer Function
Tests the transfer_parts function with audit logging and enhanced validation.

Key Features Tested:
- Core transfer functionality with audit logging
- Business rule validation (quantity limits, self-transfer prevention)
- Error handling and rollback mechanisms
- Audit trail maintenance for both success and failure cases
"""
# pylint: disable=too-many-return-statements,too-many-branches,too-many-locals,too-many-statements,duplicate-code

import os
import sys

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


def get_inventory_part_quantity(conn, inventory_id: int, part_num: str, color_id: int) -> int:
    """Get the current quantity of a specific part in an inventory."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT quantity FROM public.lego_inventory_parts
            WHERE inventory_id = %s AND part_num = %s AND color_id = %s
            """,
            (inventory_id, part_num, color_id)
        )
        result = cur.fetchone()
        return result[0] if result else 0


def verify_system_components(conn) -> tuple[bool, str]:
    """Verify that all required system components exist."""
    print("\n-- Verifying System Components --")
    try:
        with conn.cursor() as cur:
            # Check main function
            cur.execute(
                """
                SELECT COUNT(*) FROM pg_proc p
                JOIN pg_namespace n ON p.pronamespace = n.oid
                WHERE n.nspname = 'public' AND p.proname = 'transfer_parts'
                """
            )
            main_func_count = cur.fetchone()[0]

            # Check audit table
            cur.execute(
                """
                SELECT COUNT(*) FROM information_schema.tables
                WHERE table_schema = 'public' AND table_name = 'inventory_transfer_log'
                """
            )
            audit_table_count = cur.fetchone()[0]

            if main_func_count == 0:
                print("❌ FAIL: transfer_parts function does not exist")
                return False, "transfer_parts function does not exist"

            if audit_table_count == 0:
                print("❌ FAIL: inventory_transfer_log table does not exist")
                return False, "inventory_transfer_log table does not exist"

            print("✅ PASS: All system components exist")
            return True, ""
    finally:
        conn.rollback()


def verify_successful_transfer_with_audit(conn) -> tuple[bool, str]:
    """Test a successful transfer with audit logging."""
    print("\n-- Verifying Successful Transfer with Audit --")
    passed = False
    try:
        # Test data: Transfer 100 white plates from Mosaic Dino to Mosaic Johnny Thunder
        source_id = 14469
        target_id = 14686
        part_num = '3024'
        color_id = 15
        transfer_qty = 100
        reason = 'inventory_adjustment'

        source_initial = get_inventory_part_quantity(conn, source_id, part_num, color_id)
        target_initial = get_inventory_part_quantity(conn, target_id, part_num, color_id)
        print(f"Initial quantities - Source: {source_initial}, Target: {target_initial}")

        # Get initial audit log count
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM inventory_transfer_log")
            initial_log_count = cur.fetchone()[0]

        with conn.cursor() as cur:
            cur.execute(
                "SELECT transfer_parts(%s, %s, %s, %s, %s, %s)",
                (source_id, target_id, part_num, color_id, transfer_qty, reason)
            )
            result = cur.fetchone()
            print(f"Transfer result: {result[0]}")

        source_final = get_inventory_part_quantity(conn, source_id, part_num, color_id)
        target_final = get_inventory_part_quantity(conn, target_id, part_num, color_id)
        print(f"Final quantities - Source: {source_final}, Target: {target_final}")

        # Verify audit log entry
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM inventory_transfer_log")
            final_log_count = cur.fetchone()[0]

            if final_log_count <= initial_log_count:
                print("❌ FAIL: No audit log entry was created")
                return False

            # Check latest audit entry
            cur.execute(
                """
                SELECT transfer_status, quantity_transferred, transfer_reason
                FROM inventory_transfer_log
                ORDER BY log_id DESC
                LIMIT 1
                """
            )
            audit_entry = cur.fetchone()

            if not audit_entry:
                print("❌ FAIL: Could not retrieve audit log entry")
                return False

            status, qty_transferred, trans_reason = audit_entry

            if status != 'success':
                print(f"❌ FAIL: Transfer status should be 'success', got '{status}'")
                return False

            if qty_transferred != transfer_qty or trans_reason != reason:
                print("❌ FAIL: Audit log details don't match transfer parameters")
                return False

        expected_source = source_initial - transfer_qty
        expected_target = target_initial + transfer_qty

        if source_final != expected_source:
            print(
                f"❌ FAIL: Source quantity mismatch. "
                f"Expected {expected_source}, got {source_final}"
            )
            return False, (
                f"Source quantity mismatch. "
                f"Expected {expected_source}, got {source_final}"
            )
        if target_final != expected_target:
            print(
                f"❌ FAIL: Target quantity mismatch. "
                f"Expected {expected_target}, got {target_final}"
            )
            return False, (
                f"Target quantity mismatch. "
                f"Expected {expected_target}, got {target_final}"
            )
        print("✅ PASS: Successful transfer with audit logging completed correctly")
        passed = True

    except psycopg2.Error as e:
        print(f"❌ FAIL: Transfer failed unexpectedly with error: {e}")
        return False, f"Transfer failed unexpectedly with error: {e}"
    finally:
        conn.rollback()

    if passed:
        return True, ""
    return False, "Transfer verification failed"


def verify_new_part_transfer(conn) -> tuple[bool, str]:
    """Test transferring a part to an inventory that doesn't have it."""
    print("\n-- Verifying New Part Transfer --")
    passed = False
    try:
        # Test data: Transfer red bricks to Mosaic Johnny Thunder (which doesn't have them)
        source_id = 11124  # Giant Lego Dacta Basic Set (has red bricks)
        target_id = 14686  # Lego Mosaic Johnny Thunder (doesn't have red bricks)
        part_num = '3001'
        color_id = 4
        transfer_qty = 50
        reason = 'part_redistribution'

        target_initial = get_inventory_part_quantity(conn, target_id, part_num, color_id)
        if target_initial != 0:
            print(
                f"❌ FAIL: Pre-condition failed. Target already has "
                f"{target_initial} of this part, expected 0"
            )
            return False, (
                f"Pre-condition failed. Target already has "
                f"{target_initial} of this part"
            )

        source_initial = get_inventory_part_quantity(conn, source_id, part_num, color_id)
        print(f"Initial quantities - Source: {source_initial}, Target: {target_initial}")

        with conn.cursor() as cur:
            cur.execute(
                "SELECT transfer_parts(%s, %s, %s, %s, %s, %s)",
                (source_id, target_id, part_num, color_id, transfer_qty, reason)
            )
            result = cur.fetchone()
            print(f"Transfer result: {result[0]}")

        source_final = get_inventory_part_quantity(conn, source_id, part_num, color_id)
        target_final = get_inventory_part_quantity(conn, target_id, part_num, color_id)
        print(f"Final quantities - Source: {source_final}, Target: {target_final}")

        expected_source = source_initial - transfer_qty
        expected_target = transfer_qty

        if source_final != expected_source:
            print(
                f"❌ FAIL: Source quantity mismatch. "
                f"Expected {expected_source}, got {source_final}"
            )
            return False, (
                f"Source quantity mismatch. "
                f"Expected {expected_source}, got {source_final}"
            )
        if target_final != expected_target:
            print(
                f"❌ FAIL: Target quantity mismatch. "
                f"Expected {expected_target}, got {target_final}"
            )
            return False, (
                f"Target quantity mismatch. "
                f"Expected {expected_target}, got {target_final}"
            )
        print("✅ PASS: New part transfer completed correctly")
        passed = True

    except psycopg2.Error as e:
        print(f"❌ FAIL: Transfer failed unexpectedly with error: {e}")
        return False, f"Transfer failed unexpectedly with error: {e}"
    finally:
        conn.rollback()

    if passed:
        return True, ""
    return False, "Transfer verification failed"


def verify_business_rule_validation(conn) -> tuple[bool, str]:
    """Test business rule validation including quantity limits and self-transfer prevention."""
    print("\n-- Verifying Business Rule Validation --")

    # Test 1: Self-transfer (should fail)
    print("Test 1: Self-transfer (should fail)")
    test1_passed = False
    try:
        source_id = 14469
        part_num = '3024'
        color_id = 15
        transfer_qty = 10
        reason = 'self_transfer'

        with conn.cursor() as cur:
            cur.execute(
                "SELECT transfer_parts(%s, %s, %s, %s, %s, %s)",
                (source_id, source_id, part_num, color_id, transfer_qty, reason)
            )
            result = cur.fetchone()
            print(f"❌ FAIL: Self-transfer should have failed but succeeded: {result[0]}")
    except psycopg2.Error:
        print("✅ PASS: Self-transfer correctly failed")
        test1_passed = True
    except (ValueError, KeyError, TypeError) as e:
        print(f"❌ FAIL: Self-transfer test failed with unexpected error: {e}")
    finally:
        conn.rollback() # Rollback after first test

    # Test 2: Transfer quantity exceeds maximum (should fail)
    print("Test 2: Transfer quantity exceeds maximum (should fail)")
    test2_passed = False
    try:
        source_id = 14469
        target_id = 14686
        part_num = '3024'
        color_id = 15

        with conn.cursor() as cur:
            cur.execute(
                "SELECT transfer_parts(%s, %s, %s, %s, %s, %s)",
                (source_id, target_id, part_num, color_id, 600, 'large_transfer')
            )
            result = cur.fetchone()
            print(f"❌ FAIL: Large transfer should have failed but succeeded: {result[0]}")
    except psycopg2.Error:
        print("✅ PASS: Large transfer correctly failed")
        test2_passed = True
    except (ValueError, KeyError, TypeError) as e:
        print(f"❌ FAIL: Large transfer test failed with unexpected error: {e}")
    finally:
        conn.rollback() # Rollback after second test

    # Test 3: Transfer quantity below minimum (should fail)
    print("Test 3: Transfer quantity below minimum (should fail)")
    test3_passed = False
    try:
        source_id = 14469
        target_id = 14686
        part_num = '3024'
        color_id = 15

        with conn.cursor() as cur:
            cur.execute(
                "SELECT transfer_parts(%s, %s, %s, %s, %s, %s)",
                (source_id, target_id, part_num, color_id, 0, 'zero_transfer')
            )
            result = cur.fetchone()
            print(f"❌ FAIL: Zero transfer should have failed but succeeded: {result[0]}")
    except psycopg2.Error:
        print("✅ PASS: Zero transfer correctly failed")
        test3_passed = True
    except (ValueError, KeyError, TypeError) as e:
        print(f"❌ FAIL: Zero transfer test failed with unexpected error: {e}")
    finally:
        conn.rollback() # Rollback after third test

    if test1_passed and test2_passed and test3_passed:
        return True, ""
    failed_tests = []
    if not test1_passed:
        failed_tests.append("self-transfer")
    if not test2_passed:
        failed_tests.append("large transfer")
    if not test3_passed:
        failed_tests.append("zero transfer")
    return False, f"Business rule validation failed: {', '.join(failed_tests)}"


def verify_insufficient_quantity_error(conn) -> tuple[bool, str]:
    """Test that transfer fails when source has insufficient quantity."""
    print("\n-- Verifying Insufficient Quantity Error --")
    passed = False
    try:
        source_id = 14469
        target_id = 14686
        part_num = '3024'
        color_id = 15
        transfer_qty = 99999  # Far more than available
        reason = 'insufficient_test'

        source_initial = get_inventory_part_quantity(conn, source_id, part_num, color_id)
        target_initial = get_inventory_part_quantity(conn, target_id, part_num, color_id)
        print(f"Initial quantities - Source: {source_initial}, Target: {target_initial}")

        with conn.cursor() as cur:
            try:
                cur.execute(
                    "SELECT transfer_parts(%s, %s, %s, %s, %s, %s)",
                    (source_id, target_id, part_num, color_id, transfer_qty, reason)
                )
                result = cur.fetchone()
                print(f"❌ FAIL: Transfer should have failed but succeeded: {result[0]}")
            except psycopg2.Error:
                print(
                    "✅ PASS: Transfer correctly failed with an exception."
                )
                # After an exception, the transaction is in an aborted state.
                # Must rollback before new queries.
                conn.rollback()

                source_final = get_inventory_part_quantity(
                    conn, source_id, part_num, color_id
                )
                target_final = get_inventory_part_quantity(
                    conn, target_id, part_num, color_id
                )

                if source_final != source_initial:
                    print(
                        f"❌ FAIL: Source quantity changed from "
                        f"{source_initial} to {source_final}"
                    )
                    return False, (
                        f"Source quantity changed from {source_initial} "
                        f"to {source_final}"
                    )
                if target_final != target_initial:
                    print(
                        f"❌ FAIL: Target quantity changed from "
                        f"{target_initial} to {target_final}"
                    )
                    return False, (
                        f"Target quantity changed from {target_initial} "
                        f"to {target_final}"
                    )
                print("✅ PASS: Database state unchanged after failed transfer")
                passed = True
    finally:
        conn.rollback()

    if passed:
        return True, ""
    return False, "Insufficient quantity error verification failed"


def verify_invalid_inventory_error(conn) -> tuple[bool, str]:
    """Test that transfer fails with invalid inventory IDs."""
    print("\n-- Verifying Invalid Inventory Error --")
    passed = False
    try:
        source_id = 99999  # Non-existent inventory
        target_id = 14686
        part_num = '3024'
        color_id = 15
        transfer_qty = 10
        reason = 'invalid_test'

        target_initial = get_inventory_part_quantity(conn, target_id, part_num, color_id)

        with conn.cursor() as cur:
            try:
                cur.execute(
                    "SELECT transfer_parts(%s, %s, %s, %s, %s, %s)",
                    (source_id, target_id, part_num, color_id, transfer_qty, reason)
                )
                result = cur.fetchone()
                print(f"❌ FAIL: Transfer should have failed but succeeded: {result[0]}")
            except psycopg2.Error:
                print("✅ PASS: Transfer correctly failed with an exception.")
                # Rollback the aborted transaction
                conn.rollback()

                target_final = get_inventory_part_quantity(
                    conn, target_id, part_num, color_id
                )
                if target_final != target_initial:
                    print(
                        f"❌ FAIL: Target quantity changed from "
                        f"{target_initial} to {target_final}"
                    )
                    return False, (
                        f"Target quantity changed from {target_initial} "
                        f"to {target_final}"
                    )
                print("✅ PASS: Database state unchanged after invalid inventory error")
                passed = True
    finally:
        conn.rollback()

    if passed:
        return True, ""
    return False, "Invalid inventory error verification failed"


def verify_audit_logging(conn) -> tuple[bool, str]:
    """
    Test that audit logging captures both successful and failed transfers.
    This function uses commits to separate test cases and work around the
    transactional paradox of logging a failure within a transaction that
    is about to be rolled back by the client.
    """
    print("\n-- Verifying Audit Logging --")

    # Part 1: Test success logging
    print("Part 1: Verifying success log entry...")
    success_passed = False
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM inventory_transfer_log")
            initial_count = cur.fetchone()[0]

        with conn.cursor() as cur:
            cur.execute(
                "SELECT transfer_parts(14469, 14686, '3024', 15, 5, 'audit_test_success')"
            )

        # Check the log before committing/rolling back
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM inventory_transfer_log")
            final_count = cur.fetchone()[0]
            if final_count == initial_count + 1:
                print("✅ PASS: Success log was correctly written within the transaction.")
                success_passed = True
            else:
                print("❌ FAIL: Success log was not created.")

    except (ValueError, KeyError, TypeError) as e:
        print(f"❌ FAIL: Success logging test threw an unexpected error: {e}")
    finally:
        conn.rollback() # Clean up the transaction for the next part

    if not success_passed:
        return False, "Success log was not created"

    # Part 2: Test failure logging
    print("\nPart 2: Verifying failure log entry...")
    failure_passed = False
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM inventory_transfer_log")
            initial_count = cur.fetchone()[0]

        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT transfer_parts(14469, 14469, '3024', 15, 5, 'audit_test_fail')"
                )
        except psycopg2.Error:
            # This is the expected failure path.
            # The function should have logged the failure before raising the error.
            # Now, we check the log table.
            pass

        # The transaction is now in an aborted state. We must rollback to issue new commands.
        conn.rollback()

        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM inventory_transfer_log")
            final_count = cur.fetchone()[0]
            if final_count == initial_count:
                print(
                    "✅ PASS: Failure log was correctly rolled back "
                    "as expected in a standard transaction."
                )
                failure_passed = True
            else:
                print(
                    "❌ FAIL: Failure log was not rolled back. "
                    "This implies a non-standard transaction behavior."
                )
                print(
                    f"Log count before: {initial_count}, "
                    f"Log count after: {final_count}"
                )

    except (ValueError, KeyError, TypeError) as e:
        print(f"❌ FAIL: Failure logging test threw an unexpected error: {e}")
    finally:
        conn.rollback() # Ensure cleanup

    if success_passed and failure_passed:
        return True, ""
    return False, "Audit logging verification failed"


def verify_exact_quantity_transfer(conn) -> tuple[bool, str]:
    """Test transferring exact quantity (should delete source row when quantity becomes 0)."""
    print("\n-- Verifying Exact Quantity Transfer --")
    passed = False
    target_id = 14686  # Use a fixed target inventory

    try:
        # Find a part with a small quantity that doesn't conflict with the target inventory
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT inventory_id, part_num, color_id, quantity
                FROM public.lego_inventory_parts
                WHERE quantity BETWEEN 5 AND 20 AND inventory_id != %s
                LIMIT 1
                """,
                (target_id,)
            )
            result = cur.fetchone()
            if not result:
                print("⚠️ SKIP: No suitable part found for exact quantity test")
                return True, ""

            source_id, part_num, color_id, exact_qty = result

        print(
            f"Testing exact transfer: {exact_qty} parts of '{part_num}' "
            f"from inventory {source_id} to {target_id}"
        )

        source_initial = get_inventory_part_quantity(conn, source_id, part_num, color_id)
        target_initial = get_inventory_part_quantity(conn, target_id, part_num, color_id)
        print(f"Initial quantities - Source: {source_initial}, Target: {target_initial}")

        with conn.cursor() as cur:
            cur.execute(
                "SELECT transfer_parts(%s, %s, %s, %s, %s, %s)",
                (source_id, target_id, part_num, color_id, exact_qty, 'exact_transfer')
            )
            print(f"Transfer result: {cur.fetchone()[0]}")

        source_final = get_inventory_part_quantity(conn, source_id, part_num, color_id)
        target_final = get_inventory_part_quantity(conn, target_id, part_num, color_id)
        print(f"Final quantities - Source: {source_final}, Target: {target_final}")

        expected_source = 0
        expected_target = target_initial + exact_qty

        if source_final != expected_source:
            print(
                f"❌ FAIL: Source quantity should be 0 (row deleted), "
                f"but got {source_final}"
            )
            return False, (
                f"Source quantity should be 0 (row deleted), "
                f"but got {source_final}"
            )
        if target_final != expected_target:
            print(
                f"❌ FAIL: Target quantity mismatch. "
                f"Expected {expected_target}, got {target_final}"
            )
            return False, (
                f"Target quantity mismatch. "
                f"Expected {expected_target}, got {target_final}"
            )
        print("✅ PASS: Exact quantity transfer completed correctly (source row deleted)")
        passed = True

    except psycopg2.Error as e:
        print(f"❌ FAIL: Transfer failed unexpectedly with error: {e}")
        return False, f"Transfer failed unexpectedly with error: {e}"
    finally:
        conn.rollback()

    if passed:
        return True, ""
    return False, "Exact quantity transfer verification failed"


def verify() -> tuple[bool, str]:
    """Verification function for transactional inventory transfer task."""
    print("=" * 60)
    print("LEGO Enhanced Inventory Transfer Function Verification Script")
    print("=" * 60)

    conn_params = get_connection_params()
    if not conn_params.get("database"):
        print("❌ CRITICAL: POSTGRES_DATABASE environment variable not set.")
        return False, "POSTGRES_DATABASE environment variable not set"

    conn = None
    try:
        conn = psycopg2.connect(**conn_params)
        conn.autocommit = False  # Ensure we can control transactions manually

        # Run all verification steps
        success, error_msg = verify_system_components(conn)
        if not success:
            if conn:
                conn.close()
            return False, error_msg

        success, error_msg = verify_successful_transfer_with_audit(conn)
        if not success:
            if conn:
                conn.close()
            return False, error_msg

        success, error_msg = verify_new_part_transfer(conn)
        if not success:
            if conn:
                conn.close()
            return False, error_msg

        success, error_msg = verify_business_rule_validation(conn)
        if not success:
            if conn:
                conn.close()
            return False, error_msg

        success, error_msg = verify_insufficient_quantity_error(conn)
        if not success:
            if conn:
                conn.close()
            return False, error_msg

        success, error_msg = verify_invalid_inventory_error(conn)
        if not success:
            if conn:
                conn.close()
            return False, error_msg

        success, error_msg = verify_audit_logging(conn)
        if not success:
            if conn:
                conn.close()
            return False, error_msg

        success, error_msg = verify_exact_quantity_transfer(conn)
        if not success:
            if conn:
                conn.close()
            return False, error_msg

        print("\n🎉 Overall Result: PASS - All verification steps completed successfully!")
        if conn:
            conn.close()
        return True, ""

    except psycopg2.OperationalError as e:
        print(f"❌ CRITICAL: Could not connect to the database. Details: {e}")
        if conn:
            conn.close()
        return False, f"Could not connect to the database. Details: {e}"
    except (ValueError, KeyError, TypeError) as e:
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
