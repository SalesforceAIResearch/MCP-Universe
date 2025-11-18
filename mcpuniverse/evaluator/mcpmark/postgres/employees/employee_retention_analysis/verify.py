# pylint: disable=too-many-return-statements,duplicate-code
"""
Verification script for PostgreSQL Task 2: Employee Retention Analysis
"""

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

def verify_retention_analysis_results(conn) -> tuple[bool, str]:
    """Verify the employee retention analysis results."""
    with conn.cursor() as cur:
        # Get actual results from the created table
        cur.execute("""
            SELECT department_name, total_employees_ever, current_employees,
                   former_employees, retention_rate
            FROM employees.employee_retention_analysis
            ORDER BY department_name
        """)
        actual_results = cur.fetchall()

        # Execute ground truth query
        cur.execute("""
            SELECT
            d.dept_name AS department_name,
            COUNT(DISTINCT de.employee_id) AS total_employees_ever,
            COUNT(DISTINCT de.employee_id) FILTER (WHERE de.to_date = DATE '9999-01-01') AS current_employees,
            (COUNT(DISTINCT de.employee_id)
            - COUNT(DISTINCT de.employee_id) FILTER (WHERE de.to_date = DATE '9999-01-01')) AS former_employees,
            (COUNT(DISTINCT de.employee_id) FILTER (WHERE de.to_date = DATE '9999-01-01'))::DECIMAL
                / NULLIF(COUNT(DISTINCT de.employee_id), 0) * 100 AS retention_rate
            FROM employees.department d
            LEFT JOIN employees.department_employee de
            ON d.id = de.department_id
            GROUP BY d.id, d.dept_name
            ORDER BY d.dept_name
        """)
        expected_results = cur.fetchall()

        if len(actual_results) != len(expected_results):
            print(
                f"❌ Expected {len(expected_results)} retention analysis "
                f"results, got {len(actual_results)}"
            )
            return False, (
                f"Expected {len(expected_results)} retention analysis "
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

        print(f"✅ Employee retention analysis results are correct ({len(actual_results)} records)")
        return True, ""

def verify_high_risk_results(conn) -> tuple[bool, str]:
    """Verify the high risk employee analysis results."""
    with conn.cursor() as cur:
        # Get actual results from the created table
        cur.execute("""
            SELECT employee_id, full_name, current_department, tenure_days,
                   current_salary, risk_category
            FROM employees.high_risk_employees
            ORDER BY employee_id
        """)
        actual_results = cur.fetchall()

        # Execute ground truth query - only current employees
        cur.execute("""
            WITH current_salary AS (
            SELECT employee_id, amount AS current_amount
            FROM (
                SELECT s.*,
                    ROW_NUMBER() OVER (PARTITION BY s.employee_id
                                        ORDER BY s.from_date DESC, s.amount DESC) AS rn
                FROM employees.salary s
                WHERE s.to_date = DATE '9999-01-01'
            ) x
            WHERE rn = 1
            ),
            current_dept AS (
            SELECT employee_id, department_id
            FROM (
                SELECT de.*,
                    ROW_NUMBER() OVER (PARTITION BY de.employee_id
                                        ORDER BY de.from_date DESC, de.department_id) AS rn
                FROM employees.department_employee de
                WHERE de.to_date = DATE '9999-01-01'
            ) x
            WHERE rn = 1
            ),
            dept_retention AS (
            SELECT
                d.id   AS department_id,
                d.dept_name,
                COUNT(DISTINCT de.employee_id) AS total_employees_ever,
                COUNT(DISTINCT de.employee_id) FILTER (WHERE de.to_date = DATE '9999-01-01') AS current_employees,
                (COUNT(DISTINCT de.employee_id) FILTER (WHERE de.to_date = DATE '9999-01-01'))::NUMERIC
                / NULLIF(COUNT(DISTINCT de.employee_id), 0) * 100 AS retention_rate
            FROM employees.department d
            LEFT JOIN employees.department_employee de
                    ON de.department_id = d.id
            GROUP BY d.id, d.dept_name
            )
            SELECT
            e.id AS employee_id,
            CONCAT(e.first_name, ' ', e.last_name) AS full_name,
            d.dept_name AS current_department,
            (CURRENT_DATE - e.hire_date)::INTEGER AS tenure_days,
            cs.current_amount::INTEGER AS current_salary,
            CASE
                WHEN dr.retention_rate < 80  AND (CURRENT_DATE - e.hire_date) < 1095 THEN 'high_risk'
                WHEN dr.retention_rate < 85  AND (CURRENT_DATE - e.hire_date) < 1825 THEN 'medium_risk'
                ELSE 'low_risk'
            END AS risk_category
            FROM employees.employee e
            JOIN current_salary cs ON cs.employee_id = e.id
            JOIN current_dept   cd ON cd.employee_id = e.id
            JOIN employees.department d ON d.id = cd.department_id
            JOIN dept_retention dr ON dr.department_id = d.id
            ORDER BY e.id;
        """)
        expected_results = cur.fetchall()

        if len(actual_results) != len(expected_results):
            print(
                f"❌ Expected {len(expected_results)} high risk analysis "
                f"results, got {len(actual_results)}"
            )
            return False, (
                f"Expected {len(expected_results)} high risk analysis "
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

        print(f"✅ High risk employee analysis results are correct ({len(actual_results)} records)")
        return True, ""

def verify_turnover_trend_results(conn) -> tuple[bool, str]:
    """Verify the turnover trend analysis results."""
    with conn.cursor() as cur:
        # Get actual results from the created table
        cur.execute("""
            SELECT departure_year, departures_count, avg_tenure_days, avg_final_salary
            FROM employees.turnover_trend_analysis
            ORDER BY departure_year
        """)
        actual_results = cur.fetchall()

        # Execute ground truth query - simplified version
        cur.execute("""
            WITH last_non_current_salary AS (
            SELECT
                s.employee_id,
                s.to_date      AS departure_date,
                s.amount       AS final_salary,
                ROW_NUMBER() OVER (
                PARTITION BY s.employee_id
                ORDER BY s.to_date DESC, s.from_date DESC, s.amount DESC
                ) AS rn
            FROM employees.salary s
            WHERE s.to_date <> DATE '9999-01-01'
                AND NOT EXISTS (
                SELECT 1
                FROM employees.salary s_cur
                WHERE s_cur.employee_id = s.employee_id
                    AND s_cur.to_date = DATE '9999-01-01'
                )
            ),
            departed AS (
            SELECT employee_id, departure_date, final_salary
            FROM last_non_current_salary
            WHERE rn = 1
            ),
            with_tenure AS (
            SELECT
                e.id AS employee_id,
                d.departure_date,
                d.final_salary,
                (d.departure_date - e.hire_date)::INTEGER AS tenure_days
            FROM employees.employee e
            JOIN departed d ON d.employee_id = e.id
            )
            SELECT
            EXTRACT(YEAR FROM departure_date)::INTEGER AS departure_year,
            COUNT(*)::INTEGER                         AS departures_count,
            AVG(tenure_days)                          AS avg_tenure_days,
            AVG(final_salary)                         AS avg_final_salary
            FROM with_tenure
            WHERE departure_date BETWEEN DATE '1985-01-01' AND DATE '2002-12-31'
            GROUP BY EXTRACT(YEAR FROM departure_date)
            ORDER BY departure_year;
        """)
        expected_results = cur.fetchall()

        if len(actual_results) != len(expected_results):
            print(
                f"❌ Expected {len(expected_results)} turnover trend "
                f"results, got {len(actual_results)}"
            )
            return False, (
                f"Expected {len(expected_results)} turnover trend "
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

        print(f"✅ Turnover trend analysis results are correct ({len(actual_results)} records)")
        return True, ""

def verify() -> tuple[bool, str]:
    """Verification function for employee retention analysis task."""
    print("=" * 50)

    # Get connection parameters
    conn_params = get_connection_params()

    if not conn_params["database"]:
        print("❌ No database specified")
        return False, "No database specified"

    try:
        # Connect to database
        conn = psycopg2.connect(**conn_params)

        # Verify all three analysis results
        success, error_msg = verify_retention_analysis_results(conn)
        if not success:
            conn.close()
            return False, error_msg

        success, error_msg = verify_high_risk_results(conn)
        if not success:
            conn.close()
            return False, error_msg

        success, error_msg = verify_turnover_trend_results(conn)
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
