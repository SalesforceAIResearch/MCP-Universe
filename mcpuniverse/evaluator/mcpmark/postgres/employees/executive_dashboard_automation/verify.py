"""
Verification script for PostgreSQL Task 6: Reporting and Automation System
"""
# pylint: disable=too-many-return-statements,too-many-locals,duplicate-code

import os
import sys
from decimal import Decimal

import psycopg2  # type: ignore

def rows_match(actual_row, expected_row):
    """
    Compare two rows with appropriate tolerance.
    For Decimal types: allows 0.1 tolerance
    For date types: convert to string for comparison
    For other types: requires exact match
    """
    if len(actual_row) != len(expected_row):
        return False

    for actual, expected in zip(actual_row, expected_row):
        if isinstance(actual, Decimal) and isinstance(expected, (Decimal, float, int)):
            if abs(float(actual) - float(expected)) > 0.1:
                return False
        elif hasattr(actual, 'strftime'):  # datetime.date or datetime.datetime
            if str(actual) != str(expected):
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

def verify_materialized_views(conn) -> tuple[bool, str]:
    """Verify that materialized views were created and populated correctly."""
    with conn.cursor() as cur:
        # Check if materialized views exist
        cur.execute("""
            SELECT matviewname FROM pg_matviews
            WHERE schemaname = 'employees'
            AND matviewname IN ('exec_department_summary', 'exec_hiring_trends', 'exec_salary_distribution')
            ORDER BY matviewname
        """)
        views = [row[0] for row in cur.fetchall()]

        expected_views = [
            'exec_department_summary',
            'exec_hiring_trends',
            'exec_salary_distribution'
        ]
        if set(views) != set(expected_views):
            print(f"❌ Expected views {expected_views}, found {views}")
            return False, f"Expected views {expected_views}, found {views}"

        # Check all departments' data accuracy
        cur.execute("""
            SELECT department_name, total_employees, avg_salary, total_payroll, manager_name
            FROM employees.exec_department_summary
            ORDER BY department_name
        """)
        view_data = cur.fetchall()

        # Get actual data for all departments
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
            current_dept AS (
            SELECT DISTINCT de.employee_id, de.department_id
            FROM employees.department_employee de
            WHERE de.to_date = DATE '9999-01-01'
            ),
            current_manager AS (
            SELECT department_id,
                    CONCAT(e.first_name, ' ', e.last_name) AS manager_name
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
            )
            SELECT
            d.dept_name AS department_name,
            COUNT(cd.employee_id)::INT AS total_employees,
            AVG(cs.amount)::DECIMAL   AS avg_salary,
            COALESCE(SUM(cs.amount), 0)::BIGINT AS total_payroll,
            cm.manager_name
            FROM employees.department d
            LEFT JOIN current_dept   cd ON cd.department_id = d.id
            LEFT JOIN current_salary cs ON cs.employee_id = cd.employee_id
            LEFT JOIN current_manager cm ON cm.department_id = d.id
            GROUP BY d.id, d.dept_name, cm.manager_name
            ORDER BY d.dept_name;
        """)
        actual_data = cur.fetchall()

        if len(view_data) != len(actual_data):
            print(
                f"❌ Department count mismatch: "
                f"view={len(view_data)}, actual={len(actual_data)}"
            )
            return False, (
                f"Department count mismatch: "
                f"view={len(view_data)}, actual={len(actual_data)}"
            )

        for view_row, actual_row in zip(view_data, actual_data):
            if not rows_match(view_row, actual_row):
                print(
                    f"❌ Department summary data incorrect for {view_row[0]}: "
                    f"view={view_row}, actual={actual_row}"
                )
                return False, (
                    f"Department summary data incorrect for {view_row[0]}"
                )

        # Check all hiring trends data accuracy
        cur.execute("""
            SELECT hire_year, employees_hired, avg_starting_salary, retention_rate, top_hiring_department
            FROM employees.exec_hiring_trends
            ORDER BY hire_year
        """)
        hiring_view_data = cur.fetchall()

        # Get actual data for all years
        cur.execute("""
            WITH first_salary AS (
            SELECT employee_id, amount AS starting_salary
            FROM (
                SELECT s.*,
                    ROW_NUMBER() OVER (
                        PARTITION BY s.employee_id
                        ORDER BY s.from_date ASC, s.amount ASC
                    ) AS rn
                FROM employees.salary s
            ) x
            WHERE rn = 1
            ),
            current_emp AS (
            SELECT DISTINCT s.employee_id
            FROM employees.salary s
            WHERE s.to_date = DATE '9999-01-01'
            ),
            first_dept AS (
            SELECT employee_id, department_id
            FROM (
                SELECT de.*,
                    ROW_NUMBER() OVER (
                        PARTITION BY de.employee_id
                        ORDER BY de.from_date ASC, de.department_id
                    ) AS rn
                FROM employees.department_employee de
            ) x
            WHERE rn = 1
            ),
            hire_base AS (
            SELECT e.id AS employee_id,
                    EXTRACT(YEAR FROM e.hire_date)::INT AS hire_year
            FROM employees.employee e
            WHERE e.hire_date IS NOT NULL
            ),
            hire_by_dept_year AS (
            SELECT hb.hire_year,
                    d.dept_name,
                    COUNT(*) AS dept_hires
            FROM hire_base hb
            LEFT JOIN first_dept fd ON fd.employee_id = hb.employee_id
            LEFT JOIN employees.department d ON d.id = fd.department_id
            GROUP BY hb.hire_year, d.dept_name
            ),
            top_dept_per_year AS (
            SELECT hire_year,
                    dept_name AS top_hiring_department
            FROM (
                SELECT hire_year, dept_name, dept_hires,
                    ROW_NUMBER() OVER (
                        PARTITION BY hire_year
                        ORDER BY dept_hires DESC NULLS LAST, dept_name
                    ) AS rn
                FROM hire_by_dept_year
            ) t
            WHERE rn = 1
            )
            SELECT
            hb.hire_year,
            COUNT(*)::INT AS employees_hired,
            AVG(fs.starting_salary)::DECIMAL AS avg_starting_salary,
            (COUNT(ce.employee_id)::DECIMAL / NULLIF(COUNT(*), 0) * 100) AS retention_rate,
            td.top_hiring_department
            FROM hire_base hb
            LEFT JOIN first_salary fs   ON fs.employee_id = hb.employee_id
            LEFT JOIN current_emp ce    ON ce.employee_id = hb.employee_id
            LEFT JOIN top_dept_per_year td ON td.hire_year = hb.hire_year
            GROUP BY hb.hire_year, td.top_hiring_department
            ORDER BY hb.hire_year;
        """)
        actual_hiring_data = cur.fetchall()

        if len(hiring_view_data) != len(actual_hiring_data):
            print(
                f"❌ Hiring trends count mismatch: "
                f"view={len(hiring_view_data)}, actual={len(actual_hiring_data)}"
            )
            return False, (
                f"Hiring trends count mismatch: "
                f"view={len(hiring_view_data)}, actual={len(actual_hiring_data)}"
            )

        for hiring_view, actual_hiring in zip(hiring_view_data, actual_hiring_data):
            # Now compare all 5 fields including top_hiring_department
            if not rows_match(hiring_view, actual_hiring):
                print(
                    f"❌ Hiring trends data incorrect for year {hiring_view[0]}: "
                    f"view={hiring_view}, actual={actual_hiring}"
                )
                return False, (
                    f"Hiring trends data incorrect for year {hiring_view[0]}"
                )


        # Check all salary bands' data accuracy
        cur.execute("""
            WITH band_order AS (
            SELECT '30K-50K' AS band, 1 AS ord UNION ALL
            SELECT '50K-70K', 2 UNION ALL
            SELECT '70K-90K', 3 UNION ALL
            SELECT '90K-110K',4 UNION ALL
            SELECT '110K+',   5
            )
            SELECT salary_band, employee_count, percentage_of_workforce, most_common_title
            FROM employees.exec_salary_distribution v
            JOIN band_order bo ON bo.band = v.salary_band
            ORDER BY bo.ord;
        """)
        view_bands = cur.fetchall()

        # Calculate actual data for all bands
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
            current_title AS (
            SELECT employee_id, title
            FROM (
                SELECT t.*,
                    ROW_NUMBER() OVER (
                        PARTITION BY t.employee_id
                        ORDER BY t.from_date DESC, t.title
                    ) AS rn
                FROM employees.title t
                WHERE t.to_date = DATE '9999-01-01'
            ) x
            WHERE rn = 1
            ),
            base AS (
            SELECT cs.employee_id, cs.amount, COALESCE(ct.title, 'Unknown') AS title
            FROM current_salary cs
            LEFT JOIN current_title ct ON ct.employee_id = cs.employee_id
            ),
            banded AS (
            SELECT
                CASE
                WHEN amount <  50000 THEN '30K-50K'
                WHEN amount <  70000 THEN '50K-70K'
                WHEN amount <  90000 THEN '70K-90K'
                WHEN amount < 110000 THEN '90K-110K'
                ELSE '110K+'
                END AS salary_band,
                title,
                employee_id
            FROM base
            ),
            band_counts AS (
            SELECT salary_band, COUNT(DISTINCT employee_id) AS employee_count
            FROM banded
            GROUP BY salary_band
            ),
            title_counts AS (
            SELECT salary_band, title, COUNT(DISTINCT employee_id) AS title_count
            FROM banded
            GROUP BY salary_band, title
            ),
            top_titles AS (
            SELECT salary_band, title AS most_common_title
            FROM (
                SELECT salary_band, title, title_count,
                    ROW_NUMBER() OVER (
                        PARTITION BY salary_band
                        ORDER BY title_count DESC, title
                    ) AS rn
                FROM title_counts
            ) t
            WHERE rn = 1
            ),
            workforce AS (
            SELECT COUNT(DISTINCT employee_id) AS total_current
            FROM base
            ),
            band_order AS (
            SELECT '30K-50K' AS band, 1 AS ord UNION ALL
            SELECT '50K-70K', 2 UNION ALL
            SELECT '70K-90K', 3 UNION ALL
            SELECT '90K-110K', 4 UNION ALL
            SELECT '110K+',   5
            )
            SELECT
            bc.salary_band,
            bc.employee_count::INT AS employee_count,
            (bc.employee_count::DECIMAL / NULLIF((SELECT total_current FROM workforce), 0) * 100) AS percentage_of_workforce,
            tt.most_common_title
            FROM band_counts bc
            LEFT JOIN top_titles tt ON tt.salary_band = bc.salary_band
            LEFT JOIN band_order  bo ON bo.band = bc.salary_band
            ORDER BY bo.ord;
        """)
        actual_bands = cur.fetchall()

        # Compare view data with actual data
        if len(view_bands) != len(actual_bands):
            print(
                f"❌ Salary band count mismatch: "
                f"view={len(view_bands)}, actual={len(actual_bands)}"
            )
            return False, (
                f"Salary band count mismatch: "
                f"view={len(view_bands)}, actual={len(actual_bands)}"
            )

        for view_band, actual_band in zip(view_bands, actual_bands):
            if not rows_match(view_band, actual_band):
                print(
                    f"❌ Salary band {actual_band[0]} data incorrect: "
                    f"view={view_band}, actual={actual_band}"
                )
                return False, (
                    f"Salary band {actual_band[0]} data incorrect"
                )

        print("✅ All materialized views are created and contain correct data")
        return True, ""

def verify_stored_procedures(conn) -> tuple[bool, str]:
    """Verify that stored procedure was created."""
    with conn.cursor() as cur:
        # Check if procedure exists
        cur.execute("""
            SELECT routine_name FROM information_schema.routines
            WHERE routine_schema = 'employees'
            AND routine_type = 'FUNCTION'
            AND routine_name = 'generate_monthly_report'
        """)
        procedures = [row[0] for row in cur.fetchall()]

        if 'generate_monthly_report' not in procedures:
            print("❌ generate_monthly_report procedure not found")
            return False, "generate_monthly_report procedure not found"

        # Check if monthly_reports table exists with correct structure
        cur.execute("""
            SELECT COUNT(*) FROM information_schema.columns
            WHERE table_schema = 'employees' AND table_name = 'monthly_reports'
            AND column_name IN ('report_id', 'report_date', 'department_count', 'total_employees', 'avg_salary', 'generated_at')
        """)
        report_columns = cur.fetchone()[0]
        if report_columns != 6:
            print("❌ monthly_reports table missing required columns")
            return False, "monthly_reports table missing required columns"

        print("✅ Stored procedure and supporting table are created")
        return True, ""

def verify_triggers(conn) -> tuple[bool, str]:
    """Verify that triggers were created and fired correctly."""
    with conn.cursor() as cur:
        # Check if triggers exist
        cur.execute("""
            SELECT trigger_name FROM information_schema.triggers
            WHERE trigger_schema = 'employees'
            AND trigger_name = 'high_salary_alert'
        """)
        triggers = [row[0] for row in cur.fetchall()]

        if 'high_salary_alert' not in triggers:
            print("❌ high_salary_alert trigger not found")
            return False, "high_salary_alert trigger not found"

        # Check if trigger support table exists
        cur.execute("""
            SELECT table_name FROM information_schema.tables
            WHERE table_schema = 'employees'
            AND table_name = 'salary_alerts'
        """)
        trigger_tables = [row[0] for row in cur.fetchall()]

        if 'salary_alerts' not in trigger_tables:
            print("❌ salary_alerts table not found")
            return False, "salary_alerts table not found"

        # Check if the old salary record was properly closed
        cur.execute("""
            SELECT COUNT(*) FROM employees.salary
            WHERE employee_id = 10001 AND to_date = '2024-01-31'
        """)
        old_salary_count = cur.fetchone()[0]
        if old_salary_count == 0:
            print(
                "❌ Old salary record for employee 10001 was not properly "
                "closed with to_date='2024-01-31'"
            )
            return False, (
                "Old salary record for employee 10001 was not properly closed"
            )

        # Check if the new salary record was inserted
        cur.execute("""
            SELECT COUNT(*) FROM employees.salary
            WHERE employee_id = 10001 AND amount = 125000
            AND from_date = '2024-02-01' AND to_date = '9999-01-01'
        """)
        new_salary_count = cur.fetchone()[0]
        if new_salary_count == 0:
            print("❌ New salary record for employee 10001 with amount 125000 was not inserted")
            return False, "New salary record for employee 10001 with amount 125000 was not inserted"

        # Check if high salary alert was triggered with specific details
        cur.execute("""
            SELECT COUNT(*) FROM employees.salary_alerts
            WHERE employee_id = 10001 AND salary_amount = 125000 AND status = 'new'
        """)
        alert_count = cur.fetchone()[0]
        if alert_count == 0:
            print(
                "❌ High salary alert was not triggered correctly for "
                "employee 10001 with amount 125000"
            )
            return False, (
                "High salary alert was not triggered correctly for "
                "employee 10001"
            )

        print("✅ Trigger is created and functioning correctly")
        return True, ""

def verify_procedure_execution(conn) -> tuple[bool, str]:
    """Verify that stored procedure was executed with correct data."""
    with conn.cursor() as cur:
        # Check if monthly report data matches actual statistics
        cur.execute("""
            SELECT department_count, total_employees, avg_salary
            FROM employees.monthly_reports
            WHERE report_date = '2024-01-01'
        """)
        report_data = cur.fetchone()
        if not report_data:
            print("❌ Monthly report for 2024-01-01 was not generated")
            return False, "Monthly report for 2024-01-01 was not generated"

        # Get actual current statistics to compare
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
current_dept AS (
  SELECT DISTINCT de.employee_id, de.department_id
  FROM employees.department_employee de
  WHERE de.to_date = DATE '9999-01-01'
),
base AS (
  SELECT cd.department_id, cs.employee_id, cs.amount
  FROM current_dept cd
  JOIN current_salary cs ON cs.employee_id = cd.employee_id
)
SELECT
  COUNT(DISTINCT department_id)        AS actual_dept_count,
  COUNT(DISTINCT employee_id)          AS actual_total_employees,
  AVG(amount)::DECIMAL                 AS actual_avg_salary
FROM base;
        """)
        actual_stats = cur.fetchone()

        # Compare report data with actual data
        if not rows_match(report_data, actual_stats):
            print(f"❌ Monthly report data incorrect: expected {actual_stats}, got {report_data}")
            return False, "Monthly report data incorrect"

        print("✅ Stored procedure executed with correct data")
        return True, ""

def verify_indexes(conn) -> tuple[bool, str]:
    """Verify that performance indexes were created."""
    with conn.cursor() as cur:
        # Check for required indexes
        cur.execute("""
            SELECT indexname FROM pg_indexes
            WHERE schemaname = 'employees'
            AND tablename IN ('salary_alerts', 'monthly_reports')
            AND indexname LIKE 'idx_%'
            ORDER BY indexname
        """)
        indexes = [row[0] for row in cur.fetchall()]

        # Should have at least 2 indexes created
        if len(indexes) < 2:
            print(f"❌ Expected at least 2 performance indexes, found {len(indexes)}")
            return False, f"Expected at least 2 performance indexes, found {len(indexes)}"

        print("✅ Performance indexes are created")
        return True, ""

def verify() -> tuple[bool, str]:
    """Verification function for executive dashboard automation task."""
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
        success, error_msg = verify_materialized_views(conn)
        if not success:
            conn.close()
            return False, error_msg

        success, error_msg = verify_stored_procedures(conn)
        if not success:
            conn.close()
            return False, error_msg

        success, error_msg = verify_triggers(conn)
        if not success:
            conn.close()
            return False, error_msg

        success, error_msg = verify_procedure_execution(conn)
        if not success:
            conn.close()
            return False, error_msg

        success, error_msg = verify_indexes(conn)
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
