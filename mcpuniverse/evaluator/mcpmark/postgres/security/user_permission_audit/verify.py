"""Verification module for user permission audit task."""
# pylint: disable=too-many-branches,too-many-locals,too-many-statements,duplicate-code
import os
import sys

import psycopg2


def verify() -> tuple[bool, str]:
    """
    Verify that the security audit correctly identified all permission issues.
    """

    # Database connection parameters from environment
    db_params = {
        'host': os.getenv('POSTGRES_HOST', 'localhost'),
        'port': os.getenv('POSTGRES_PORT', '5432'),
        'user': os.getenv('POSTGRES_USERNAME', 'postgres'),
        'password': os.getenv('POSTGRES_PASSWORD', 'password'),
        'database': os.getenv('POSTGRES_DATABASE', 'postgres')
    }

    try:
        conn = psycopg2.connect(**db_params)
        cur = conn.cursor()

        print("| Verifying security audit findings...")

        # Check if security_audit_results table exists
        cur.execute("""
            SELECT EXISTS (
                SELECT FROM information_schema.tables
                WHERE table_name = 'security_audit_results'
            );
        """)

        if not cur.fetchone()[0]:
            print("FAIL: security_audit_results table not found")
            return False, "security_audit_results table not found"

        # Check if security_audit_details table exists
        cur.execute("""
            SELECT EXISTS (
                SELECT FROM information_schema.tables
                WHERE table_name = 'security_audit_details'
            );
        """)

        if not cur.fetchone()[0]:
            print("FAIL: security_audit_details table not found")
            return False, "security_audit_details table not found"

        # Get all detailed findings
        cur.execute("SELECT * FROM security_audit_details ORDER BY detail_id;")
        findings = cur.fetchall()

        if not findings:
            print("FAIL: No findings in security_audit_details table")
            return False, "No findings in security_audit_details table"

        print(f"| Found {len(findings)} audit findings")

        # Expected findings based on the ground truth:
        expected_findings = {
            # Expected dangling users
            'dangling_users': {'temp_contractor', 'old_employee', 'test_account'},

            # Expected missing permissions (should be granted)
            'missing_permissions': {
                ('analytics_user', 'user_profiles', 'SELECT'),
                ('analytics_user', 'product_catalog', 'SELECT'),
                ('analytics_user', 'order_management', 'SELECT'),
                ('marketing_user', 'product_catalog', 'SELECT'),
                ('customer_service', 'product_catalog', 'SELECT'),
                ('finance_user', 'user_profiles', 'SELECT'),
                ('product_manager', 'user_stat_analysis', 'SELECT'),
                ('security_auditor', 'audit_logs', 'SELECT'),
                ('developer_user', 'product_catalog', 'SELECT'),
                ('backup_user', 'order_management', 'SELECT'),
                ('backup_user', 'financial_transactions', 'SELECT'),
                ('backup_user', 'user_stat_analysis', 'SELECT'),
                ('backup_user', 'user_credentials', 'SELECT')
            },

            # Expected excessive permissions (should be revoked)
            'excessive_permissions': {
                ('analytics_user', 'financial_transactions', 'SELECT'),
                ('marketing_user', 'financial_transactions', 'SELECT'),
                ('customer_service', 'user_credentials', 'SELECT'),
                ('product_manager', 'financial_transactions', 'SELECT'),
                ('security_auditor', 'financial_transactions', 'UPDATE'),
                ('developer_user', 'user_credentials', 'SELECT'),
                ('developer_user', 'order_management', 'UPDATE'),
                ('backup_user', 'product_catalog', 'DELETE'),
                ('temp_contractor', 'product_catalog', 'SELECT'),
                ('temp_contractor', 'user_profiles', 'SELECT'),
                ('old_employee', 'audit_logs', 'SELECT'),
                ('old_employee', 'user_stat_analysis', 'UPDATE'),
                ('test_account', 'user_profiles', 'SELECT')
            }
        }

        found_dangling = set()
        found_missing_permissions = set()
        found_excessive_permissions = set()

        # Analyze findings
        # (detail_id, username, issue_type, table_name, permission_type,
        #  expected_access)
        for finding in findings:
            username = finding[1]
            issue_type = finding[2]
            table_name = finding[3]
            permission_type = finding[4]
            expected_access = finding[5]

            if issue_type == 'DANGLING_USER':
                found_dangling.add(username)
            elif issue_type == 'MISSING_PERMISSION' and expected_access:
                if table_name and permission_type:
                    found_missing_permissions.add((username, table_name, permission_type))
            elif issue_type == 'EXCESSIVE_PERMISSION' and not expected_access:
                if table_name and permission_type:
                    found_excessive_permissions.add((username, table_name, permission_type))

        # Verify dangling users
        missing_dangling = expected_findings['dangling_users'] - found_dangling
        _extra_dangling = found_dangling - expected_findings['dangling_users']

        # Verify missing permissions
        missing_missing_perms = expected_findings['missing_permissions'] - found_missing_permissions
        _extra_missing_perms = found_missing_permissions - expected_findings['missing_permissions']

        # Verify excessive permissions
        missing_excessive_perms = (
            expected_findings['excessive_permissions'] -
            found_excessive_permissions
        )
        _extra_excessive_perms = (
            found_excessive_permissions -
            expected_findings['excessive_permissions']
        )

        # Validate structure
        structure_valid = True
        for i, finding in enumerate(findings):
            if len(finding) != 6:  # Should have 6 columns
                print(
                    f"| FAIL: Finding {i + 1} has wrong number of columns "
                    f"(expected 6, got {len(finding)})"
                )
                structure_valid = False
                continue

            _detail_id, username, issue_type, table_name, permission_type, expected_access = finding

            if not username:
                print(f"| FAIL: Finding {i + 1} missing username")
                structure_valid = False

            if issue_type not in ['DANGLING_USER', 'MISSING_PERMISSION', 'EXCESSIVE_PERMISSION']:
                print(f"| FAIL: Finding {i + 1} invalid issue_type: {issue_type}")
                structure_valid = False

            if expected_access not in [True, False]:
                print(f"| FAIL: Finding {i + 1} invalid expected_access: {expected_access}")
                structure_valid = False

        if structure_valid:
            print("| ✓ structure is valid")

        # Check for missing findings
        all_correct = True

        print(
            f"| Expected dangling users: {expected_findings['dangling_users']} "
            f"Found: {found_dangling}"
        )
        if missing_dangling:
            print(f"| Missing dangling users: {missing_dangling}")
            all_correct = False

        print(
            f"| Expected missing permissions: "
            f"{len(expected_findings['missing_permissions'])} "
            f"Found: {len(found_missing_permissions)} "
            f"Missing: {len(missing_missing_perms)}"
        )
        if missing_missing_perms:
            print("| Missing 'missing permission' findings:")
            for perm in sorted(missing_missing_perms):
                print(f"|   - {perm[0]} should be granted {perm[2]} on {perm[1]}")
            all_correct = False

        print(
            f"| Expected excessive permissions: "
            f"{len(expected_findings['excessive_permissions'])} "
            f"Found: {len(found_excessive_permissions)} "
            f"Missing: {len(missing_excessive_perms)}"
        )
        if missing_excessive_perms:
            print("| Missing 'excessive permission' findings:")
            for perm in sorted(missing_excessive_perms):
                print(f"|   - {perm[0]} should have {perm[2]} revoked on {perm[1]}")
            all_correct = False

        # Check audit summary table
        cur.execute(
            "SELECT audit_type, total_issues, users_affected, tables_affected "
            "FROM security_audit_results ORDER BY audit_type;"
        )
        summary_results = cur.fetchall()

        # Expected summary numbers based on ground truth
        expected_summary = {
            'DANGLING_USERS': (3, 3, 0),          # 3 issues, 3 users affected, 0 tables affected
            'EXCESSIVE_PERMISSIONS': (13, 10, 7), # 13 issues, 10 users affected, 7 tables affected
            'MISSING_PERMISSIONS': (13, 8, 7)     # 13 issues, 8 users affected, 7 tables affected
        }

        summary_correct = True
        for result in summary_results:
            audit_type, total_issues, users_affected, tables_affected = result
            print(
                f"| Summary result: [{audit_type}] {total_issues} issues, "
                f"{users_affected} users affected, "
                f"{tables_affected} tables affected"
            )

            if audit_type in expected_summary:
                expected = expected_summary[audit_type]
                if (total_issues, users_affected, tables_affected) != expected:
                    print(
                        f"| FAIL: {audit_type} summary mismatch - "
                        f"Expected: {expected}, "
                        f"Got: ({total_issues}, {users_affected}, "
                        f"{tables_affected})"
                    )
                    summary_correct = False
                else:
                    print(f"| ✓ {audit_type} summary matches expected values")

        # Check exact counts match expected
        errors = []
        if len(found_dangling) != 3:
            errors.append(f"Expected 3 dangling users, found {len(found_dangling)}")
        if len(found_missing_permissions) != 13:
            errors.append(
                f"Expected 13 missing permissions, "
                f"found {len(found_missing_permissions)}"
            )
        if len(found_excessive_permissions) != 13:
            errors.append(
                f"Expected 13 excessive permissions, "
                f"found {len(found_excessive_permissions)}"
            )

        if all_correct and structure_valid and summary_correct and not errors:
            print("| ✓ All assertions passed")
            return True, ""
        error_msg = "; ".join(errors) if errors else "Security audit verification failed"
        return False, error_msg

    except (psycopg2.Error, ValueError, KeyError, TypeError) as e:
        print(f"FAIL: Error during verification: {e}")
        return False, f"Error during verification: {e}"
    finally:
        if 'cur' in locals():
            cur.close()
        if 'conn' in locals():
            conn.close()

def main():
    """Main verification function."""
    success, _error_msg = verify()
    sys.exit(0 if success else 1)

if __name__ == "__main__":
    main()
