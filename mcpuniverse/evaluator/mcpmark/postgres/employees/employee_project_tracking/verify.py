"""
Verification script for PostgreSQL Task 5: Database Schema and Data Operations
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

def verify_table_structures(conn) -> tuple[bool, str]:
    """Verify that all three tables were created with correct structure."""
    with conn.cursor() as cur:
        # Check if tables exist
        cur.execute("""
            SELECT table_name FROM information_schema.tables
            WHERE table_schema = 'employees'
            AND table_name IN ('employee_projects', 'project_assignments', 'project_milestones')
            ORDER BY table_name
        """)
        tables = [row[0] for row in cur.fetchall()]

        if len(tables) != 3:
            print(f"❌ Expected 3 tables, found {len(tables)}: {tables}")
            return False, f"Expected 3 tables, found {len(tables)}"

        # Check foreign key constraints exist
        cur.execute("""
            SELECT COUNT(*) FROM information_schema.table_constraints
            WHERE table_schema = 'employees'
            AND constraint_type = 'FOREIGN KEY'
            AND table_name IN ('project_assignments', 'project_milestones')
        """)
        fkey_count = cur.fetchone()[0]

        if fkey_count != 3:
            print(f"❌ Expected 3 foreign key constraints, found {fkey_count}")
            return False, f"Expected 3 foreign key constraints, found {fkey_count}"

        # Check if priority column exists (added in step 6)
        cur.execute("""
            SELECT COUNT(*) FROM information_schema.columns
            WHERE table_schema = 'employees' AND table_name = 'employee_projects'
            AND column_name = 'priority'
        """)
        priority_exists = cur.fetchone()[0]

        if priority_exists == 0:
            print("❌ Priority column was not added to employee_projects table")
            return False, "Priority column was not added to employee_projects table"

        print("✅ Table structures are correct")
        return True, ""

def verify_indexes(conn) -> tuple[bool, str]:
    """Verify that required indexes were created."""
    with conn.cursor() as cur:
        # Check for specific indexes
        cur.execute("""
            SELECT COUNT(*)
            FROM pg_indexes
            WHERE schemaname = 'employees'
            AND indexname IN ('idx_projects_status', 'idx_assignments_emp_proj', 'idx_milestones_due_date')
        """)
        index_count = cur.fetchone()[0]

        if index_count != 3:
            print(f"❌ Expected 3 required indexes, got {index_count}")
            return False, f"Expected 3 required indexes, got {index_count}"

        print("✅ All required indexes are present")
        return True, ""

def verify_project_data(conn) -> tuple[bool, str]:
    """Verify that project data was inserted and updated correctly."""
    with conn.cursor() as cur:
        # Check project data after updates
        cur.execute("""
            SELECT project_name, start_date, end_date, budget, status, priority
            FROM employees.employee_projects
            ORDER BY project_name
        """)
        projects = cur.fetchall()

        if len(projects) != 3:
            print(f"❌ Expected 3 projects, found {len(projects)}")
            return False, f"Expected 3 projects, found {len(projects)}"

        # Expected final state after all updates
        expected = {
            'Database Modernization': ('2024-01-15', '2024-06-30', 287500.00, 'active', 'high'),
            'Employee Portal Upgrade': ('2024-02-01', '2024-05-15', 207000.00, 'active', 'medium'),
            'HR Analytics Dashboard': ('2023-11-01', '2024-01-31', 120000.00, 'completed', 'medium')
        }

        for project in projects:
            name = project[0]
            if name not in expected:
                print(f"❌ Unexpected project: {name}")
                return False, f"Unexpected project: {name}"

            exp = expected[name]
            # Use rows_match for comparison
            expected_row = (name,) + exp
            if not rows_match(project, expected_row):
                print(f"❌ Project {name} data mismatch: expected {expected_row}, got {project}")
                return False, f"Project {name} data mismatch"

        print("✅ Project data is correct")
        return True, ""

def verify_assignment_data(conn) -> tuple[bool, str]:
    """Verify that all current employees were assigned to projects by department."""
    with conn.cursor() as cur:
        # Check total assignment count matches current employee count
        cur.execute("""
            SELECT COUNT(*) FROM employees.project_assignments
        """)
        assignment_count = cur.fetchone()[0]

        cur.execute("""
            SELECT COUNT(DISTINCT de.employee_id)
            FROM employees.department_employee de
            WHERE de.to_date = '9999-01-01'
        """)
        current_employee_count = cur.fetchone()[0]

        if assignment_count != current_employee_count:
            print(f"❌ Expected {current_employee_count} assignments, found {assignment_count}")
            return False, f"Expected {current_employee_count} assignments, found {assignment_count}"

        # Check department-project mapping
        cur.execute("""
            SELECT d.dept_name, pa.project_id, pa.role, pa.allocation_percentage, COUNT(*)
            FROM employees.project_assignments pa
            JOIN employees.department_employee de ON pa.employee_id = de.employee_id AND de.to_date = '9999-01-01'
            JOIN employees.department d ON de.department_id = d.id
            JOIN employees.employee_projects ep ON pa.project_id = ep.project_id
            GROUP BY d.dept_name, pa.project_id, pa.role, pa.allocation_percentage
            ORDER BY d.dept_name
        """)
        dept_assignments = cur.fetchall()

        # Expected department-project mappings
        expected_mappings = {
            'Development': (1, 'Developer', 80),
            'Human Resources': (2, 'Business Analyst', 60),
            'Marketing': (3, 'Marketing Specialist', 40),
            'Finance': (1, 'Financial Analyst', 30),
            'Sales': (2, 'Sales Representative', 50),
            'Research': (3, 'Research Analyst', 70),
            'Production': (1, 'Production Coordinator', 45),
            'Quality Management': (2, 'QA Specialist', 85),
            'Customer Service': (3, 'Customer Success', 35)
        }

        dept_found = {}
        for assignment in dept_assignments:
            dept_name, project_id, role, allocation, _ = assignment  # Ignore count
            if dept_name in dept_found:
                print(f"❌ Department {dept_name} has multiple assignments")
                return False, f"Department {dept_name} has multiple assignments"
            dept_found[dept_name] = (project_id, role, allocation)

        for dept, expected in expected_mappings.items():
            if dept not in dept_found:
                print(f"❌ Department {dept} has no assignments")
                return False, f"Department {dept} has no assignments"
            if dept_found[dept] != expected:
                print(
                    f"❌ Department {dept} assignment mismatch: "
                    f"expected {expected}, got {dept_found[dept]}"
                )
                return False, f"Department {dept} assignment mismatch"

        # Check that all assignments have correct assigned_date
        cur.execute("""
            SELECT COUNT(*) FROM employees.project_assignments
            WHERE assigned_date != '2024-01-01'
        """)
        wrong_date_count = cur.fetchone()[0]

        if wrong_date_count > 0:
            print(f"❌ {wrong_date_count} assignments have incorrect assigned_date")
            return False, f"{wrong_date_count} assignments have incorrect assigned_date"

        print("✅ Assignment data is correct")
        return True, ""

def verify_milestone_data(conn) -> tuple[bool, str]:
    """Verify that milestone data was inserted and updated correctly."""
    with conn.cursor() as cur:
        cur.execute("""
            SELECT project_id, milestone_name, due_date, completed
            FROM employees.project_milestones
            ORDER BY project_id, milestone_name
        """)
        milestones = cur.fetchall()

        if len(milestones) != 6:
            print(f"❌ Expected 6 milestones, found {len(milestones)}")
            return False, f"Expected 6 milestones, found {len(milestones)}"

        # Expected milestones
        expected_milestones = {
            (1, 'Design Phase Complete'): ('2024-03-01', False),
            (1, 'Implementation Complete'): ('2024-05-15', False),
            (2, 'UI/UX Approval'): ('2024-03-15', False),
            (2, 'Beta Testing'): ('2024-04-30', False),
            (3, 'Data Collection'): ('2023-12-15', True),  # Should be completed
            (3, 'Dashboard Launch'): ('2024-01-25', False)
        }

        for milestone in milestones:
            project_id, name, due_date, completed = milestone
            key = (project_id, name)

            if key not in expected_milestones:
                print(f"❌ Unexpected milestone: {key}")
                return False, f"Unexpected milestone: {key}"

            expected_due, expected_completed = expected_milestones[key]
            if str(due_date) != expected_due or completed != expected_completed:
                print(
                    f"❌ Milestone {name} mismatch: "
                    f"expected ({expected_due}, {expected_completed}), "
                    f"got ({due_date}, {completed})"
                )
                return False, f"Milestone {name} mismatch"

        print("✅ Milestone data is correct")
        return True, ""

def verify() -> tuple[bool, str]:
    """Verification function for employee project tracking task."""
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
        success, error_msg = verify_table_structures(conn)
        if not success:
            conn.close()
            return False, error_msg

        success, error_msg = verify_indexes(conn)
        if not success:
            conn.close()
            return False, error_msg

        success, error_msg = verify_project_data(conn)
        if not success:
            conn.close()
            return False, error_msg

        success, error_msg = verify_assignment_data(conn)
        if not success:
            conn.close()
            return False, error_msg

        success, error_msg = verify_milestone_data(conn)
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
