"""
Verification script for PostgreSQL Task 3: Employee Demographics Report
"""
# pylint: disable=too-many-return-statements,duplicate-code

import os
import sys
from decimal import Decimal

import psycopg2  # type: ignore

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

def verify_gender_statistics_results(conn) -> tuple[bool, str]:
    """Verify the gender statistics results."""
    with conn.cursor() as cur:
        # Get actual results from the created table
        cur.execute("""
            SELECT gender, total_employees, current_employees, percentage_of_workforce
            FROM employees.gender_statistics
            ORDER BY gender
        """)
        actual_results = cur.fetchall()

        # Execute ground truth query
        cur.execute("""
            WITH current_emp AS (
            SELECT DISTINCT s.employee_id
            FROM employees.salary s
            WHERE s.to_date = DATE '9999-01-01'
            ),
            total_current AS (
            SELECT COUNT(*) AS cnt
            FROM current_emp
            )
            SELECT
            e.gender::varchar AS gender,
            COUNT(*) AS total_employees,
            COUNT(*) FILTER (WHERE ce.employee_id IS NOT NULL) AS current_employees,
            (COUNT(*) FILTER (WHERE ce.employee_id IS NOT NULL))::DECIMAL
                / NULLIF((SELECT cnt FROM total_current), 0) * 100 AS percentage_of_workforce
            FROM employees.employee e
            LEFT JOIN current_emp ce ON ce.employee_id = e.id
            WHERE e.gender IN ('M','F')
            GROUP BY e.gender
            ORDER BY gender;
        """)
        expected_results = cur.fetchall()

        if len(actual_results) != len(expected_results):
            print(
                f"❌ Expected {len(expected_results)} gender statistics "
                f"results, got {len(actual_results)}"
            )
            return False, (
                f"Expected {len(expected_results)} gender statistics "
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

        print(f"✅ Gender statistics results are correct ({len(actual_results)} records)")
        return True, ""

def verify_age_group_results(conn) -> tuple[bool, str]:
    """Verify the age group analysis results."""
    with conn.cursor() as cur:
        # Get actual results from the created table
        cur.execute("""
            SELECT age_group, employee_count, avg_salary, avg_tenure_days
            FROM employees.age_group_analysis
            ORDER BY age_group
        """)
        actual_results = cur.fetchall()

        # Execute ground truth query
        cur.execute("""
WITH current_salary AS (
  SELECT employee_id, amount
  FROM (
    SELECT s.*,
           ROW_NUMBER() OVER (
             PARTITION BY s.employee_id
             ORDER BY s.from_date DESC, s.amount DESC
           ) AS rn
    FROM employees.salary s
    WHERE s.to_date = DATE '9999-01-01'
  ) x
  WHERE rn = 1
),
emp_age AS (
  SELECT
    e.id AS employee_id,
    e.hire_date,
    EXTRACT(YEAR FROM AGE(CURRENT_DATE, e.birth_date))::INT AS age_years
  FROM employees.employee e
  WHERE e.birth_date IS NOT NULL
)
SELECT
  CASE
    WHEN a.age_years BETWEEN 20 AND 29 THEN '20-29'
    WHEN a.age_years BETWEEN 30 AND 39 THEN '30-39'
    WHEN a.age_years BETWEEN 40 AND 49 THEN '40-49'
    WHEN a.age_years BETWEEN 50 AND 59 THEN '50-59'
    WHEN a.age_years >= 60 THEN '60+'
  END AS age_group,
  COUNT(*)::INT AS employee_count,
  AVG(cs.amount) AS avg_salary,
  AVG((CURRENT_DATE - a.hire_date)::INT) AS avg_tenure_days
FROM emp_age a
JOIN current_salary cs ON cs.employee_id = a.employee_id
WHERE a.age_years >= 20
GROUP BY 1
ORDER BY 1;
        """)
        expected_results = cur.fetchall()

        if len(actual_results) != len(expected_results):
            print(
                f"❌ Expected {len(expected_results)} age group results, "
                f"got {len(actual_results)}"
            )
            return False, (
                f"Expected {len(expected_results)} age group results, "
                f"got {len(actual_results)}"
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

        print(f"✅ Age group analysis results are correct ({len(actual_results)} records)")
        return True, ""

def verify_birth_month_results(conn) -> tuple[bool, str]:
    """Verify the birth month distribution results."""
    with conn.cursor() as cur:
        # Get actual results from the created table
        cur.execute("""
            SELECT birth_month, month_name, employee_count, current_employee_count
            FROM employees.birth_month_distribution
            ORDER BY birth_month
        """)
        actual_results = cur.fetchall()

        # Execute ground truth query
        cur.execute("""
            WITH current_emp AS (
            SELECT DISTINCT s.employee_id
            FROM employees.salary s
            WHERE s.to_date = DATE '9999-01-01'
            ),
            months AS (
            SELECT gs AS birth_month
            FROM generate_series(1, 12) AS gs
            )
            SELECT
            m.birth_month::INTEGER AS birth_month,
            CASE m.birth_month
                WHEN 1 THEN 'January'   WHEN 2 THEN 'February' WHEN 3 THEN 'March'
                WHEN 4 THEN 'April'     WHEN 5 THEN 'May'      WHEN 6 THEN 'June'
                WHEN 7 THEN 'July'      WHEN 8 THEN 'August'   WHEN 9 THEN 'September'
                WHEN 10 THEN 'October'  WHEN 11 THEN 'November'WHEN 12 THEN 'December'
            END AS month_name,
            COUNT(e.id)::INTEGER AS employee_count,
            COUNT(ce.employee_id)::INTEGER AS current_employee_count
            FROM months m
            LEFT JOIN employees.employee e
            ON EXTRACT(MONTH FROM e.birth_date) = m.birth_month
            LEFT JOIN current_emp ce
            ON ce.employee_id = e.id
            GROUP BY m.birth_month
            ORDER BY m.birth_month;
        """)
        expected_results = cur.fetchall()

        if len(actual_results) != len(expected_results):
            print(
                f"❌ Expected {len(expected_results)} birth month results, "
                f"got {len(actual_results)}"
            )
            return False, (
                f"Expected {len(expected_results)} birth month results, "
                f"got {len(actual_results)}"
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

        print(f"✅ Birth month distribution results are correct ({len(actual_results)} records)")
        return True, ""

def verify_hiring_year_results(conn) -> tuple[bool, str]:
    """Verify the hiring year summary results."""
    with conn.cursor() as cur:
        # Get actual results from the created table
        cur.execute("""
            SELECT hire_year, employees_hired, still_employed, retention_rate
            FROM employees.hiring_year_summary
            ORDER BY hire_year
        """)
        actual_results = cur.fetchall()

        # Execute ground truth query
        cur.execute("""
            WITH current_emp AS (
            SELECT DISTINCT s.employee_id
            FROM employees.salary s
            WHERE s.to_date = DATE '9999-01-01'
            ),
            base AS (
            SELECT e.id, EXTRACT(YEAR FROM e.hire_date)::INT AS hire_year
            FROM employees.employee e
            WHERE e.hire_date IS NOT NULL
            )
            SELECT
            b.hire_year,
            COUNT(*)::INT AS employees_hired,
            COUNT(*) FILTER (WHERE ce.employee_id IS NOT NULL)::INT AS still_employed,
            (COUNT(*) FILTER (WHERE ce.employee_id IS NOT NULL))::DECIMAL
                / NULLIF(COUNT(*), 0) * 100 AS retention_rate
            FROM base b
            LEFT JOIN current_emp ce ON ce.employee_id = b.id
            GROUP BY b.hire_year
            ORDER BY b.hire_year;
        """)
        expected_results = cur.fetchall()

        if len(actual_results) != len(expected_results):
            print(
                f"❌ Expected {len(expected_results)} hiring year results, "
                f"got {len(actual_results)}"
            )
            return False, (
                f"Expected {len(expected_results)} hiring year results, "
                f"got {len(actual_results)}"
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

        print(f"✅ Hiring year summary results are correct ({len(actual_results)} records)")
        return True, ""

def verify() -> tuple[bool, str]:
    """Verification function for employee demographics report task."""
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
        success, error_msg = verify_gender_statistics_results(conn)
        if not success:
            conn.close()
            return False, error_msg

        success, error_msg = verify_age_group_results(conn)
        if not success:
            conn.close()
            return False, error_msg

        success, error_msg = verify_birth_month_results(conn)
        if not success:
            conn.close()
            return False, error_msg

        success, error_msg = verify_hiring_year_results(conn)
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
