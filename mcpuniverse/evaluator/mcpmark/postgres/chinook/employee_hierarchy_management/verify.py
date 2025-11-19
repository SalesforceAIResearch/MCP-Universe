"""
Verification script for PostgreSQL Task 3: Employee Hierarchy Management
"""
# pylint: disable=too-many-return-statements,duplicate-code

import os
import sys
from datetime import datetime
from decimal import Decimal

import psycopg2  # type: ignore

def rows_match(actual_row, expected_row):
    """
    Compare two rows with appropriate tolerance.
    For Decimal types: allows 0.01 tolerance
    For other types: requires exact match
    """
    if len(actual_row) != len(expected_row):
        return False

    for actual, expected in zip(actual_row, expected_row):
        if isinstance(actual, Decimal) and isinstance(expected, Decimal):
            if abs(float(actual) - float(expected)) > 0.01:
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

def verify_employee_count_and_titles(conn) -> tuple[bool, str]:
    """Verify the final employee count and title changes."""
    with conn.cursor() as cur:
        # Check the final verification query results
        cur.execute("""
            SELECT
                COUNT(*) as total_employees,
                COUNT(CASE WHEN "Title" = 'CEO' THEN 1 END) as ceo_count,
                COUNT(CASE WHEN "Title" = 'IT Specialist' THEN 1 END) as it_specialist_count,
                COUNT(CASE WHEN "ReportsTo" = 1 THEN 1 END) as reports_to_ceo
            FROM "Employee"
        """)
        result = cur.fetchone()

        total_employees, ceo_count, it_specialist_count, reports_to_ceo = result

        # Expected: total_employees = 9, ceo_count = 1, it_specialist_count = 1, reports_to_ceo = 4
        if total_employees != 9:
            print(f"❌ Expected 9 total employees, got {total_employees}")
            return False, f"Expected 9 total employees, got {total_employees}"

        if ceo_count != 1:
            print(f"❌ Expected 1 CEO, got {ceo_count}")
            return False, f"Expected 1 CEO, got {ceo_count}"

        if it_specialist_count != 0:
            print(f"❌ Expected 0 IT Specialists, got {it_specialist_count}")
            return False, f"Expected 0 IT Specialists, got {it_specialist_count}"

        if reports_to_ceo != 4:
            print(f"❌ Expected 4 employees reporting to CEO, got {reports_to_ceo}")
            return False, f"Expected 4 employees reporting to CEO, got {reports_to_ceo}"

        print("✅ Employee count and title verification passed")
        return True, ""

def verify_specific_employees(conn) -> tuple[bool, str]:
    """Verify specific employee records and modifications."""
    with conn.cursor() as cur:
        # Check all employee fields in one query
        cur.execute("""
            SELECT "EmployeeId", "LastName", "FirstName", "Title", "ReportsTo", "BirthDate",
                   "HireDate", "Address", "City", "State", "Country", "PostalCode",
                   "Phone", "Fax", "Email"
            FROM "Employee"
            WHERE "EmployeeId" IN (1, 2, 9, 10)
            ORDER BY "EmployeeId"
        """)
        employees = cur.fetchall()

        expected = [
            # Andrew Adams (ID 1) - Title changes to 'CEO', phone stays
            # original, ReportsTo stays None
            (
                1, 'Adams', 'Andrew', 'CEO', None,
                datetime(1962, 2, 18), datetime(2002, 8, 14),
                '11120 Jasper Ave NW', 'Edmonton', 'AB', 'Canada',
                'T5K 2N1', '+1 (780) 428-9482', '+1 (780) 428-3457',
                'andrew@chinookcorp.com'
            ),
            # Nancy Edwards (ID 2) - Phone changes, title stays
            # 'Sales Manager', ReportsTo stays 1
            (
                2, 'Edwards', 'Nancy', 'Sales Manager', 1,
                datetime(1958, 12, 8), datetime(2002, 5, 1),
                '825 8 Ave SW', 'Calgary', 'AB', 'Canada', 'T2P 2T3',
                '+1 (403) 555-9999', '+1 (403) 262-3322',
                'nancy@chinookcorp.com'
            ),
            # Sarah Johnson - all new data, final ReportsTo = 1
            # (changed in step 4)
            (
                9, 'Johnson', 'Sarah', 'Sales Support Agent', 1,
                datetime(1985, 3, 15), datetime(2009, 1, 10),
                '123 Oak Street', 'Calgary', 'AB', 'Canada', 'T2P 5G3',
                '+1 (403) 555-0123', '+1 (403) 555-0124',
                'sarah.johnson@chinookcorp.com'
            ),
            # Mike Chen - all new data, final ReportsTo = 1
            # (changed in step 4)
            (
                10, 'Chen', 'Mike', 'Sales Support Agent', 1,
                datetime(1982, 8, 22), datetime(2009, 1, 10),
                '456 Pine Ave', 'Calgary', 'AB', 'Canada', 'T2P 5G4',
                '+1 (403) 555-0125', '+1 (403) 555-0126',
                'mike.chen@chinookcorp.com'
            )
        ]

        if len(employees) != 4:
            print(f"❌ Expected 4 key employees, found {len(employees)}")
            return False, f"Expected 4 key employees, found {len(employees)}"

        # Full field comparison for all employees using rows_match
        for actual, expected_emp in zip(employees, expected):
            if not rows_match(actual, expected_emp):
                print(f"❌ Employee {actual[0]} row mismatch: expected {expected_emp}, got {actual}")
                return False, f"Employee {actual[0]} row mismatch"

        print("✅ Specific employee verification passed - all fields match exactly")
        return True, ""

def verify_customer_assignments(conn) -> tuple[bool, str]:
    """Verify customer support representative assignments."""
    with conn.cursor() as cur:
        # Check customers 1, 2, 3 are assigned to Sarah (ID 9)
        cur.execute("""
            SELECT COUNT(*)
            FROM "Customer"
            WHERE "CustomerId" IN (1, 2, 3) AND "SupportRepId" = 9
        """)
        sarah_customers = cur.fetchone()[0]

        if sarah_customers != 3:
            print(f"❌ Expected 3 customers assigned to Sarah Johnson, got {sarah_customers}")
            return False, f"Expected 3 customers assigned to Sarah Johnson, got {sarah_customers}"

        # Check customers 4, 5, 6 are assigned to Mike (ID 10)
        cur.execute("""
            SELECT COUNT(*)
            FROM "Customer"
            WHERE "CustomerId" IN (4, 5, 6) AND "SupportRepId" = 10
        """)
        mike_customers = cur.fetchone()[0]

        if mike_customers != 3:
            print(f"❌ Expected 3 customers assigned to Mike Chen, got {mike_customers}")
            return False, f"Expected 3 customers assigned to Mike Chen, got {mike_customers}"

        print("✅ Customer assignment verification passed")
        return True, ""

def verify_performance_table(conn) -> tuple[bool, str]:
    """Verify the employee_performance table exists and has correct data."""
    with conn.cursor() as cur:
        try:
            # Get all performance records
            cur.execute("""
                SELECT employee_id, customers_assigned, performance_score
                FROM employee_performance
                ORDER BY employee_id
            """)
            actual_results = cur.fetchall()

            # Get actual customer counts for verification
            cur.execute("""
                SELECT "SupportRepId", COUNT(*)
                FROM "Customer"
                WHERE "SupportRepId" IN (9, 10)
                GROUP BY "SupportRepId"
                ORDER BY "SupportRepId"
            """)
            customer_counts = dict(cur.fetchall())

            expected = [
                (9, customer_counts.get(9, 0), Decimal('4.5')),  # Sarah Johnson
                (10, customer_counts.get(10, 0), Decimal('4.2'))  # Mike Chen
            ]

            if len(actual_results) != 2:
                print(f"❌ Expected 2 performance records, got {len(actual_results)}")
                return False, f"Expected 2 performance records, got {len(actual_results)}"

            for actual, expected_row in zip(actual_results, expected):
                if not rows_match(actual, expected_row):
                    print(f"❌ Performance record mismatch: expected {expected_row}, got {actual}")
                    return False, "Performance record mismatch"

            print("✅ Employee performance table verification passed")
            return True, ""

        except psycopg2.Error as e:
            print(f"❌ Employee performance table verification failed: {e}")
            return False, f"Employee performance table verification failed: {e}"

def verify_employee_deletion_and_promotion(conn) -> tuple[bool, str]:
    """Verify Robert King deletion and Laura Callahan promotion."""
    with conn.cursor() as cur:
        try:
            # Verify Robert King (ID 7) is deleted
            cur.execute("""
                SELECT COUNT(*) FROM "Employee" WHERE "EmployeeId" = 7
            """)
            if cur.fetchone()[0] != 0:
                print("❌ Robert King (EmployeeId = 7) should be deleted")
                return False, "Robert King (EmployeeId = 7) should be deleted"

            # Verify Laura Callahan (ID 8) promotion
            cur.execute("""
                SELECT "Title" FROM "Employee" WHERE "EmployeeId" = 8
            """)
            laura_title = cur.fetchone()
            if not laura_title or laura_title[0] != 'Senior IT Specialist':
                title_got = laura_title[0] if laura_title else None
                print(
                    f"❌ Laura Callahan should have title "
                    f"'Senior IT Specialist', got: {title_got}"
                )
                return False, (
                    "Laura Callahan should have title "
                    "'Senior IT Specialist'"
                )

            print("✅ Employee deletion and promotion verification passed")
            return True, ""

        except psycopg2.Error as e:
            print(f"❌ Employee deletion/promotion verification failed: {e}")
            return False, f"Employee deletion/promotion verification failed: {e}"

def verify_salary_column(conn) -> tuple[bool, str]:
    """Verify salary column exists and has correct values."""
    with conn.cursor() as cur:
        try:
            # Check if salary column exists and get all salary values
            cur.execute("""
                SELECT "EmployeeId", salary
                FROM "Employee"
                ORDER BY "EmployeeId"
            """)
            salary_data = cur.fetchall()

            # Verify Laura (ID 8) has 75000.00, others have 50000.00
            for emp_id, salary in salary_data:
                expected_salary = (
                    Decimal('75000.00') if emp_id == 8
                    else Decimal('50000.00')
                )
                if salary != expected_salary:
                    print(
                        f"❌ Employee {emp_id} salary should be "
                        f"{expected_salary}, got {salary}"
                    )
                    return False, (
                        f"Employee {emp_id} salary should be "
                        f"{expected_salary}, got {salary}"
                    )

            print("✅ Salary column verification passed")
            return True, ""

        except psycopg2.Error as e:
            print(f"❌ Salary column verification failed: {e}")
            return False, f"Salary column verification failed: {e}"

def verify() -> tuple[bool, str]:
    """Verification function for employee hierarchy management task."""
    print("=" * 50)
    print("Verifying Task 3: Employee Hierarchy Management")
    print("=" * 50)

    # Get connection parameters
    conn_params = get_connection_params()

    if not conn_params["database"]:
        print("❌ No database specified")
        return False, "No database specified"

    try:
        # Connect to database
        conn = psycopg2.connect(**conn_params)

        # Run verification checks
        success, error_msg = verify_employee_count_and_titles(conn)
        if not success:
            conn.close()
            return False, error_msg

        success, error_msg = verify_specific_employees(conn)
        if not success:
            conn.close()
            return False, error_msg

        success, error_msg = verify_customer_assignments(conn)
        if not success:
            conn.close()
            return False, error_msg

        success, error_msg = verify_performance_table(conn)
        if not success:
            conn.close()
            return False, error_msg

        success, error_msg = verify_employee_deletion_and_promotion(conn)
        if not success:
            conn.close()
            return False, error_msg

        success, error_msg = verify_salary_column(conn)
        if not success:
            conn.close()
            return False, error_msg

        conn.close()

        print("\n🎉 Task verification: PASS")
        print("All employee hierarchy management operations completed correctly!")
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
