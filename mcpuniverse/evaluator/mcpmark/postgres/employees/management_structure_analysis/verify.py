"""
Verification script for PostgreSQL Task 4: Management Structure Analysis
"""
# pylint: disable=too-many-return-statements,duplicate-code

import os
import sys
from decimal import Decimal

import psycopg2

def rows_match(actual_row, expected_row):
    """
    Compare two rows with appropriate tolerance.
    For Decimal types: allows 0.1 tolerance
    For other types: requires exact match
    """
    if len(actual_row) != len(expected_row):
        return False

    for actual, expected in zip(actual_row, expected_row):
        if isinstance(actual, Decimal) and isinstance(expected, Decimal):
            if abs(float(actual) - float(expected)) > 0.1:
                return False
        elif actual != expected:
            return False

    return True

def get_connection_params() -> dict:
    """Get database connection parameters."""
    return {
        "host": os.getenv("POSTGRES_HOST", "localhost"),
        "port": int(os.getenv("POSTGRES_PORT", "5432")),
        "database": os.getenv("POSTGRES_DATABASE"),
        "user": os.getenv("POSTGRES_USERNAME"),
        "password": os.getenv("POSTGRES_PASSWORD")
    }

def verify_manager_profile_results(conn) -> tuple[bool, str]:
    """Verify the manager profile results."""
    with conn.cursor() as cur:
        # Get actual results from the created table
        cur.execute("""
            SELECT manager_id, manager_name, current_department,
                   management_periods, current_manager
            FROM employees.manager_profile
            ORDER BY manager_id
        """)
        actual_results = cur.fetchall()

        # Execute ground truth query
        cur.execute("""
            WITH dm AS (
            SELECT dm.employee_id,
                    dm.department_id,
                    dm.from_date,
                    dm.to_date
            FROM employees.department_manager dm
            ),
            manager_periods AS (
            SELECT employee_id, COUNT(*)::INT AS management_periods
            FROM dm
            GROUP BY employee_id
            ),
            current_assignment AS (
            SELECT employee_id, department_id
            FROM (
                SELECT d.*,
                    ROW_NUMBER() OVER (
                        PARTITION BY d.employee_id
                        ORDER BY d.from_date DESC, d.department_id
                    ) AS rn
                FROM dm d
                WHERE d.to_date = DATE '9999-01-01'
            ) x
            WHERE rn = 1
            ),
            manager_names AS (
            SELECT e.id AS manager_id,
                    CONCAT(e.first_name, ' ', e.last_name) AS manager_name
            FROM employees.employee e
            WHERE EXISTS (SELECT 1 FROM dm WHERE employee_id = e.id)
            )
            SELECT
            mn.manager_id,
            mn.manager_name,
            d.dept_name AS current_department,
            mp.management_periods,
            (d.dept_name IS NOT NULL) AS current_manager
            FROM manager_names mn
            JOIN manager_periods mp ON mp.employee_id = mn.manager_id
            LEFT JOIN current_assignment ca ON ca.employee_id = mn.manager_id
            LEFT JOIN employees.department d ON d.id = ca.department_id
            ORDER BY mn.manager_id;
        """)
        expected_results = cur.fetchall()

        if len(actual_results) != len(expected_results):
            print(
                f"❌ Expected {len(expected_results)} manager profile "
                f"results, got {len(actual_results)}"
            )
            return False, (
                f"Expected {len(expected_results)} manager profile "
                f"results, got {len(actual_results)}"
            )

        mismatches = 0
        for i, (actual, expected) in enumerate(zip(actual_results, expected_results)):
            if not rows_match(actual, expected):
                if mismatches < 5:  # Only show first 5 mismatches
                    print(f"❌ Row {i+1} mismatch: expected {expected}, got {actual}")
                mismatches += 1

        if mismatches > 0:
            print(f"❌ Total mismatches: {mismatches}")
            return False, f"Total mismatches: {mismatches}"

        print(f"✅ Manager profile results are correct ({len(actual_results)} records)")
        return True, ""

def verify_department_leadership_results(conn) -> tuple[bool, str]:
    """Verify the department leadership results."""
    with conn.cursor() as cur:
        # Get actual results from the created table
        cur.execute("""
            SELECT department_name, current_manager_name, manager_start_date,
                   total_historical_managers
            FROM employees.department_leadership
            ORDER BY department_name
        """)
        actual_results = cur.fetchall()

        # Execute ground truth query
        cur.execute("""
            WITH current_mgr AS (
            SELECT department_id,
                    CONCAT(e.first_name, ' ', e.last_name) AS current_manager_name,
                    dm.from_date AS manager_start_date
            FROM (
                SELECT dm.*,
                    ROW_NUMBER() OVER (
                        PARTITION BY dm.department_id
                        ORDER BY dm.from_date DESC, dm.employee_id
                    ) AS rn
                FROM employees.department_manager dm
                WHERE dm.to_date = DATE '9999-01-01'
            ) dm
            JOIN employees.employee e ON e.id = dm.employee_id
            WHERE dm.rn = 1
            ),
            hist AS (
            SELECT dm.department_id, COUNT(DISTINCT dm.employee_id)::INT AS total_historical_managers
            FROM employees.department_manager dm
            GROUP BY dm.department_id
            )
            SELECT
            d.dept_name                              AS department_name,
            cm.current_manager_name,
            cm.manager_start_date,
            COALESCE(h.total_historical_managers,0)  AS total_historical_managers
            FROM employees.department d
            LEFT JOIN current_mgr cm ON cm.department_id = d.id
            LEFT JOIN hist        h  ON h.department_id = d.id
            ORDER BY d.dept_name;
        """)
        expected_results = cur.fetchall()

        if len(actual_results) != len(expected_results):
            print(
                f"❌ Expected {len(expected_results)} department "
                f"leadership results, got {len(actual_results)}"
            )
            return False, (
                f"Expected {len(expected_results)} department "
                f"leadership results, got {len(actual_results)}"
            )

        mismatches = 0
        for i, (actual, expected) in enumerate(zip(actual_results, expected_results)):
            if not rows_match(actual, expected):
                if mismatches < 5:  # Only show first 5 mismatches
                    print(f"❌ Row {i+1} mismatch: expected {expected}, got {actual}")
                mismatches += 1

        if mismatches > 0:
            print(f"❌ Total mismatches: {mismatches}")
            return False, f"Total mismatches: {mismatches}"

        print(f"✅ Department leadership results are correct ({len(actual_results)} records)")
        return True, ""

def verify_management_transitions_results(conn) -> tuple[bool, str]:
    """Verify the management transitions results."""
    with conn.cursor() as cur:
        # Get actual results from the created table
        cur.execute("""
            SELECT department_name, transition_year, outgoing_manager, incoming_manager, transition_gap_days
            FROM employees.management_transitions
            ORDER BY department_name, transition_year
        """)
        actual_results = cur.fetchall()

        # Execute ground truth query
        cur.execute("""
            WITH mgr AS (
            SELECT
                d.id AS department_id,
                d.dept_name,
                dm.employee_id,
                dm.from_date,
                dm.to_date,
                CONCAT(e.first_name, ' ', e.last_name) AS manager_name
            FROM employees.department_manager dm
            JOIN employees.department d ON d.id = dm.department_id
            JOIN employees.employee  e ON e.id = dm.employee_id
            ),
            ordered AS (
            SELECT
                department_id,
                dept_name,
                employee_id,
                manager_name,
                from_date,
                to_date,
                ROW_NUMBER() OVER (
                PARTITION BY department_id
                ORDER BY from_date, to_date, employee_id
                ) AS rn,
                LEAD(manager_name) OVER (
                PARTITION BY department_id
                ORDER BY from_date, to_date, employee_id
                ) AS next_manager_name,
                LEAD(from_date) OVER (
                PARTITION BY department_id
                ORDER BY from_date, to_date, employee_id
                ) AS next_from_date
            FROM mgr
            )
            SELECT
            o.dept_name                                   AS department_name,
            EXTRACT(YEAR FROM o.to_date)::INT             AS transition_year,
            o.manager_name                                AS outgoing_manager,
            COALESCE(o.next_manager_name, 'No Successor') AS incoming_manager,
            COALESCE(GREATEST((o.next_from_date - o.to_date - 1), 0), 0)::INT AS transition_gap_days
            FROM ordered o
            WHERE o.to_date <> DATE '9999-01-01'
            ORDER BY department_name, transition_year;
        """)
        expected_results = cur.fetchall()

        if len(actual_results) != len(expected_results):
            print(
                f"❌ Expected {len(expected_results)} management "
                f"transitions results, got {len(actual_results)}"
            )
            return False, (
                f"Expected {len(expected_results)} management "
                f"transitions results, got {len(actual_results)}"
            )

        mismatches = 0
        for i, (actual, expected) in enumerate(zip(actual_results, expected_results)):
            if not rows_match(actual, expected):
                if mismatches < 5:  # Only show first 5 mismatches
                    print(f"❌ Row {i+1} mismatch: expected {expected}, got {actual}")
                mismatches += 1

        if mismatches > 0:
            print(f"❌ Total mismatches: {mismatches}")
            return False, f"Total mismatches: {mismatches}"

        print(f"✅ Management transitions results are correct ({len(actual_results)} records)")
        return True, ""

def verify_span_of_control_results(conn) -> tuple[bool, str]:
    """Verify the span of control results."""
    with conn.cursor() as cur:
        # Get actual results from the created table
        cur.execute("""
            SELECT manager_id, manager_name, department_name, total_employees,
                   current_employees, management_load
            FROM employees.span_of_control
            ORDER BY manager_id
        """)
        actual_results = cur.fetchall()

        # Execute ground truth query
        cur.execute("""
            WITH dept_total AS (
            SELECT de.department_id, COUNT(DISTINCT de.employee_id)::INT AS total_employees
            FROM employees.department_employee de
            GROUP BY de.department_id
            ),
            dept_current AS (
            SELECT de.department_id, COUNT(DISTINCT de.employee_id)::INT AS current_employees
            FROM employees.department_employee de
            JOIN employees.salary s
                ON s.employee_id = de.employee_id
            AND s.to_date = DATE '9999-01-01'
            WHERE de.to_date = DATE '9999-01-01'
            GROUP BY de.department_id
            )
            SELECT
            dm.employee_id AS manager_id,
            CONCAT(e.first_name, ' ', e.last_name) AS manager_name,
            d.dept_name AS department_name,
            COALESCE(dt.total_employees, 0)  AS total_employees,
            COALESCE(dc.current_employees, 0) AS current_employees,
            CASE
                WHEN COALESCE(dc.current_employees, 0) < 5000  THEN 'light'
                WHEN COALESCE(dc.current_employees, 0) <= 15000 THEN 'moderate'
                ELSE 'heavy'
            END AS management_load
            FROM employees.department_manager dm
            JOIN employees.employee  e ON e.id = dm.employee_id
            JOIN employees.department d ON d.id = dm.department_id
            LEFT JOIN dept_total  dt ON dt.department_id = dm.department_id
            LEFT JOIN dept_current dc ON dc.department_id = dm.department_id
            WHERE dm.to_date = DATE '9999-01-01'
            ORDER BY dm.employee_id, d.dept_name;
        """)
        expected_results = cur.fetchall()

        if len(actual_results) != len(expected_results):
            print(
                f"❌ Expected {len(expected_results)} span of control "
                f"results, got {len(actual_results)}"
            )
            return False, (
                f"Expected {len(expected_results)} span of control "
                f"results, got {len(actual_results)}"
            )

        mismatches = 0
        for i, (actual, expected) in enumerate(zip(actual_results, expected_results)):
            if not rows_match(actual, expected):
                if mismatches < 5:  # Only show first 5 mismatches
                    print(f"❌ Row {i+1} mismatch: expected {expected}, got {actual}")
                mismatches += 1

        if mismatches > 0:
            print(f"❌ Total mismatches: {mismatches}")
            return False, f"Total mismatches: {mismatches}"

        print(f"✅ Span of control results are correct ({len(actual_results)} records)")
        return True, ""

def verify() -> tuple[bool, str]:
    """Verification function for management structure analysis task."""
    print("=" * 50)

    # Get connection parameters
    conn_params = get_connection_params()

    if not conn_params["database"]:
        print("❌ No database specified")
        return False, "No database specified"

    try:
        # Connect to database
        conn = psycopg2.connect(**conn_params)

        # Verify all four analysis results
        success, error_msg = verify_manager_profile_results(conn)
        if not success:
            conn.close()
            return False, error_msg

        success, error_msg = verify_department_leadership_results(conn)
        if not success:
            conn.close()
            return False, error_msg

        success, error_msg = verify_management_transitions_results(conn)
        if not success:
            conn.close()
            return False, error_msg

        success, error_msg = verify_span_of_control_results(conn)
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
