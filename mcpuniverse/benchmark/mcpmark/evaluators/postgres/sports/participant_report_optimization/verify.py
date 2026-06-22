"""
Verification script for PostgreSQL Sports Task 3: Query Performance Optimization
"""
# pylint: disable=too-many-return-statements,duplicate-code

import os
import sys
from decimal import Decimal

import psycopg2  # type: ignore

def rows_match(actual_row, expected_row):
    """
    Compare two rows with appropriate tolerance.
    For Decimal types: allows 0.001 tolerance
    For other types: requires exact match
    """
    if len(actual_row) != len(expected_row):
        return False

    for actual, expected in zip(actual_row, expected_row):
        if isinstance(actual, Decimal) and isinstance(expected, Decimal):
            if abs(float(actual) - float(expected)) > 0.001:
                return False
        elif isinstance(actual, float) and isinstance(expected, float):
            if abs(actual - expected) > 0.001:
                return False
        elif actual != expected:
            return False

    return True

def get_connection_params() -> dict:
    """Get database connection parameters."""
    return {
        "host": os.getenv("POSTGRES_HOST", "localhost"),
        "port": int(os.getenv("POSTGRES_PORT", "5432")),
        "database": os.getenv("POSTGRES_DATABASE", "sports"),
        "user": os.getenv("POSTGRES_USERNAME", "postgres"),
        "password": os.getenv("POSTGRES_PASSWORD", "postgres")
    }

def verify_report_data(conn) -> tuple[bool, str]:
    """Verify the report table contains the expected data."""
    with conn.cursor() as cur:
        # Get actual results from the report table
        cur.execute("""
            SELECT participant_id, event_count, stat_count, stat_type_count, last_event_date
            FROM participant_performance_report
            ORDER BY participant_id
        """)
        actual_results = cur.fetchall()

        if len(actual_results) == 0:
            print("❌ Report table is empty")
            return False, "Report table is empty"

        # Execute ground truth query
        cur.execute("""
            SELECT
                pe.participant_id,
                COUNT(pe.event_id) as event_count,
                (SELECT COUNT(*) FROM stats s WHERE s.stat_holder_id = pe.participant_id AND s.stat_holder_type = 'persons') as stat_count,
                (SELECT COUNT(DISTINCT s.stat_repository_type) FROM stats s WHERE s.stat_holder_id = pe.participant_id AND s.stat_holder_type = 'persons') as stat_type_count,
                (SELECT MAX(e.start_date_time) FROM events e JOIN participants_events pe2 ON e.id = pe2.event_id WHERE pe2.participant_id = pe.participant_id) as last_event_date
            FROM participants_events pe
            WHERE pe.participant_id <= 50
            GROUP BY pe.participant_id
            ORDER BY pe.participant_id
        """)
        expected_results = cur.fetchall()

        if len(actual_results) != len(expected_results):
            print(
                f"❌ Expected {len(expected_results)} report records, "
                f"got {len(actual_results)}"
            )
            return False, (
                f"Expected {len(expected_results)} report records, "
                f"got {len(actual_results)}"
            )

        mismatches = 0
        for actual, expected in zip(actual_results, expected_results):
            if not rows_match(actual, expected):
                if mismatches < 5:
                    print(f"❌ Row mismatch: expected {expected}, got {actual}")
                mismatches += 1

        if mismatches > 0:
            print(f"❌ Total mismatches in report data: {mismatches}")
            return False, f"Total mismatches in report data: {mismatches}"

        print(f"✅ Report data is correct ({len(actual_results)} records)")
        return True, ""

def verify_performance_optimization(conn) -> tuple[bool, str]:
    """Verify that key performance optimization indexes have been implemented."""
    with conn.cursor() as cur:
        print("\n🔍 Checking for critical performance indexes...")

        # Check 1: participants_events.participant_id index (critical for subqueries)
        cur.execute("""
            SELECT indexname, indexdef
            FROM pg_indexes
            WHERE schemaname = 'public'
            AND tablename = 'participants_events'
            AND indexdef LIKE '%participant_id%'
        """)
        participant_indexes = cur.fetchall()
        has_participant_index = len(participant_indexes) > 0

        # Check 2: stats table optimization (critical for subquery filtering)
        cur.execute("""
            SELECT indexname, indexdef
            FROM pg_indexes
            WHERE schemaname = 'public'
            AND tablename = 'stats'
            AND indexdef LIKE '%stat_holder_type%'
            AND indexdef LIKE '%stat_holder_id%'
        """)
        stats_indexes = cur.fetchall()
        has_stats_index = len(stats_indexes) > 0

        # Report findings
        critical_indexes_found = 0

        if has_participant_index:
            print("✅ Found participant filtering index on participants_events.participant_id")
            critical_indexes_found += 1
        else:
            print("❌ Missing critical index on participants_events.participant_id")

        if has_stats_index:
            print("✅ Found subquery optimization index on stats table")
            critical_indexes_found += 1
        else:
            print("❌ Missing critical index on stats table")

        # Must have both critical indexes for this subquery-heavy query
        if critical_indexes_found >= 2:
            print(
                f"\n✅ Performance optimization: PASS "
                f"({critical_indexes_found}/2 critical indexes found)"
            )
            return True, ""
        print(
            f"\n❌ Performance optimization: FAIL "
            f"({critical_indexes_found}/2 critical indexes found)"
        )
        print("   Create these critical indexes:")
        print("   - CREATE INDEX ON participants_events(participant_id);")
        print(
            "   - CREATE INDEX ON stats(stat_holder_type, stat_holder_id);"
        )
        return False, (
            f"Performance optimization failed: "
            f"{critical_indexes_found}/2 critical indexes found"
        )

def verify() -> tuple[bool, str]:
    """Verification function for participant report optimization task."""
    print("=" * 50)
    print("Verifying Sports Task 3: Query Performance Optimization")
    print("=" * 50)

    # Get connection parameters
    conn_params = get_connection_params()

    if not conn_params["database"]:
        print("❌ No database specified")
        return False, "No database specified"

    try:
        # Connect to database
        conn = psycopg2.connect(**conn_params)

        # Verify all components
        success, error_msg = verify_report_data(conn)
        if not success:
            conn.close()
            return False, error_msg

        success, error_msg = verify_performance_optimization(conn)
        if not success:
            conn.close()
            return False, error_msg

        conn.close()

        print("\n🎉 Task verification: PASS")
        return True, ""

    except psycopg2.Error as e:
        print(f"❌ Database error: {e}")
        return False, f"Database error: {e}"
    except (ValueError, KeyError, TypeError) as e:
        print(f"❌ Verification error: {e}")
        return False, f"Verification error: {e}"

def main():
    """Main verification function."""
    success, _error_msg = verify()
    if success:
        sys.exit(0)
    else:
        sys.exit(1)

if __name__ == "__main__":
    main()
