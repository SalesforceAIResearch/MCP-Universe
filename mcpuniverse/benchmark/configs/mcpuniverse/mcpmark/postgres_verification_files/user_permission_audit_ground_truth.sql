-- Ground Truth Solution: Complete Security Audit Implementation
-- This includes comprehensive PostgreSQL user, role, and permission discovery

/*
================================================================================
PERMISSION MODEL DOCUMENTATION
================================================================================

## Current Permission State
| Username          | Table                  | Permission | Status  | Reason                                    |
|-------------------|------------------------|------------|---------|-------------------------------------------|
| analytics_user    | user_stat_analysis     | SELECT     | EXISTS  | Correctly granted                         |
| analytics_user    | user_profiles          | SELECT     | MISSING | Permission was revoked                    |
| analytics_user    | financial_transactions | SELECT     | EXISTS  | Should be revoked - no business need     |
| marketing_user    | user_profiles          | SELECT     | EXISTS  | Correctly granted                         |
| marketing_user    | user_stat_analysis     | SELECT     | EXISTS  | Correctly granted                         |
| marketing_user    | product_catalog        | SELECT     | MISSING | Permission was revoked                    |
| marketing_user    | financial_transactions | SELECT     | EXISTS  | Should be revoked - security risk        |
| customer_service  | user_profiles          | SELECT     | EXISTS  | Correctly granted                         |
| customer_service  | user_profiles          | UPDATE     | EXISTS  | Correctly granted                         |
| customer_service  | order_management       | SELECT     | EXISTS  | Correctly granted                         |
| customer_service  | order_management       | INSERT     | EXISTS  | Correctly granted                         |
| customer_service  | order_management       | UPDATE     | EXISTS  | Correctly granted                         |
| customer_service  | product_catalog        | SELECT     | MISSING | Permission was revoked                    |
| customer_service  | user_credentials       | SELECT     | EXISTS  | Should be revoked - security risk        |
| finance_user      | financial_transactions | SELECT     | EXISTS  | Correctly granted                         |
| finance_user      | order_management       | SELECT     | EXISTS  | Correctly granted                         |
| finance_user      | user_profiles          | SELECT     | MISSING | Permission was revoked                    |
| product_manager   | product_catalog        | SELECT     | EXISTS  | Correctly granted                         |
| product_manager   | product_catalog        | INSERT     | EXISTS  | Correctly granted                         |
| product_manager   | product_catalog        | UPDATE     | EXISTS  | Correctly granted                         |
| product_manager   | product_catalog        | DELETE     | EXISTS  | Correctly granted                         |
| product_manager   | order_management       | SELECT     | EXISTS  | Correctly granted                         |
| product_manager   | financial_transactions | SELECT     | EXISTS  | Should be revoked - no business need     |
| security_auditor  | user_credentials       | SELECT     | EXISTS  | Correctly granted                         |
| security_auditor  | user_profiles          | SELECT     | EXISTS  | Correctly granted                         |
| security_auditor  | audit_logs             | SELECT     | MISSING | Permission was revoked                    |
| security_auditor  | financial_transactions | UPDATE     | EXISTS  | Should be revoked - excessive privilege  |
| developer_user    | user_profiles          | SELECT     | EXISTS  | Correctly granted                         |
| developer_user    | product_catalog        | SELECT     | MISSING | Permission was revoked                    |
| developer_user    | user_credentials       | SELECT     | EXISTS  | Should be revoked - security risk        |
| developer_user    | order_management       | UPDATE     | EXISTS  | Should be revoked - no business need     |
| backup_user       | user_profiles          | SELECT     | EXISTS  | Correctly granted                         |
| backup_user       | product_catalog        | SELECT     | EXISTS  | Correctly granted                         |
| backup_user       | audit_logs             | SELECT     | EXISTS  | Correctly granted                         |
| backup_user       | order_management       | SELECT     | MISSING | Permission was revoked                    |
| backup_user       | product_catalog        | DELETE     | EXISTS  | Should be revoked - backup should be read-only |
| temp_contractor   | product_catalog        | SELECT     | EXISTS  | Should be revoked - user is inactive     |
| temp_contractor   | user_profiles          | SELECT     | EXISTS  | Should be revoked - user is inactive     |
| old_employee      | audit_logs             | SELECT     | EXISTS  | Should be revoked - user is inactive     |
| old_employee      | user_stat_analysis     | UPDATE     | EXISTS  | Should be revoked - user is inactive     |
| test_account      | user_profiles          | SELECT     | EXISTS  | Should be revoked - test account          |

## Expected Permission State
| Username          | Table                  | Permission | Justification                                                |
|-------------------|------------------------|------------|--------------------------------------------------------------|
| analytics_user    | user_profiles          | SELECT     | Analytics team needs customer data for user behavior analysis|
| analytics_user    | user_stat_analysis     | SELECT     | Core analytics data required for reporting                   |
| analytics_user    | product_catalog        | SELECT     | Product performance analysis and customer preferences        |
| analytics_user    | order_management       | SELECT     | Sales trend analysis and customer purchasing patterns        |
| marketing_user    | user_profiles          | SELECT     | Customer segmentation and personalized marketing campaigns   |
| marketing_user    | user_stat_analysis     | SELECT     | Campaign effectiveness analysis and user behavior tracking   |
| marketing_user    | product_catalog        | SELECT     | Product promotion planning and marketing material creation   |
| customer_service  | user_profiles          | SELECT     | Customer identity verification and support                   |
| customer_service  | user_profiles          | UPDATE     | Update customer information and resolve account issues       |
| customer_service  | order_management       | SELECT     | Order status inquiries and customer support                  |
| customer_service  | order_management       | INSERT     | Create orders for customers over phone                       |
| customer_service  | order_management       | UPDATE     | Update order status and resolve order issues                 |
| customer_service  | product_catalog        | SELECT     | Product information for customer questions and support       |
| finance_user      | financial_transactions | SELECT     | Financial reporting, auditing, and compliance               |
| finance_user      | order_management       | SELECT     | Revenue reconciliation and financial analysis                |
| finance_user      | user_profiles          | SELECT     | Customer financial analysis and credit assessment            |
| product_manager   | product_catalog        | SELECT     | Product information access and management                    |
| product_manager   | product_catalog        | INSERT     | Add new products to catalog                                  |
| product_manager   | product_catalog        | UPDATE     | Update product details, pricing, and specifications         |
| product_manager   | product_catalog        | DELETE     | Remove discontinued or obsolete products                     |
| product_manager   | order_management       | SELECT     | Product sales analysis and demand forecasting               |
| product_manager   | user_stat_analysis     | SELECT     | Product usage analytics and customer behavior insights       |
| security_auditor  | audit_logs             | SELECT     | Security monitoring and incident investigation               |
| security_auditor  | user_credentials       | SELECT     | Security auditing and compliance verification               |
| security_auditor  | user_profiles          | SELECT     | User account auditing and security incident investigation    |
| developer_user    | user_profiles          | SELECT     | Application development and testing with realistic data      |
| developer_user    | product_catalog        | SELECT     | Application development and testing with product data        |
| backup_user       | user_profiles          | SELECT     | Complete data backup coverage for business continuity       |
| backup_user       | product_catalog        | SELECT     | Complete data backup coverage for business continuity       |
| backup_user       | order_management       | SELECT     | Complete data backup coverage for business continuity       |
| backup_user       | financial_transactions | SELECT     | Complete data backup coverage for business continuity       |
| backup_user       | user_stat_analysis     | SELECT     | Complete data backup coverage for business continuity       |
| backup_user       | audit_logs             | SELECT     | Complete data backup coverage for business continuity       |
| backup_user       | user_credentials       | SELECT     | Complete data backup coverage for business continuity       |

Notes:
- temp_contractor, old_employee, test_account should have NO permissions (accounts should be removed)
- All excessive permissions should be revoked for security compliance
- Missing permissions should be granted based on business role requirements

================================================================================
*/

BEGIN;

-- ============================================================================
-- CREATE AUDIT RESULTS TABLES
-- ============================================================================

CREATE TABLE security_audit_results (
    audit_id SERIAL PRIMARY KEY,
    audit_type VARCHAR(50) NOT NULL, -- 'DANGLING_USERS', 'MISSING_PERMISSIONS', 'EXCESSIVE_PERMISSIONS'
    total_issues INTEGER NOT NULL,
    users_affected INTEGER NOT NULL,
    tables_affected INTEGER NOT NULL
);

CREATE TABLE security_audit_details (
    detail_id SERIAL PRIMARY KEY,
    username VARCHAR(50) NOT NULL,
    issue_type VARCHAR(50) NOT NULL, -- 'DANGLING_USER', 'MISSING_PERMISSION', 'EXCESSIVE_PERMISSION'
    table_name VARCHAR(50), -- NULL for dangling users
    permission_type VARCHAR(20), -- 'SELECT', 'INSERT', 'UPDATE', 'DELETE', NULL for dangling users
    expected_access BOOLEAN NOT NULL -- TRUE if user should have access, FALSE if should not
);

-- ============================================================================
-- DISCOVER DATABASE USERS AND ROLES
-- ============================================================================

CREATE TEMP TABLE temp_user_discovery AS
SELECT DISTINCT
    COALESCE(u.usename, r.rolname) as username,
    COALESCE(u.usesuper, r.rolsuper) as is_superuser,
    COALESCE(u.usecreatedb, r.rolcreatedb) as can_create_db,
    r.rolname as role_name,
    u.usename as user_name,
    CASE 
        WHEN COALESCE(u.usename, r.rolname) LIKE '%analytics%' THEN 'Analytics Team'
        WHEN COALESCE(u.usename, r.rolname) LIKE '%marketing%' THEN 'Marketing Department'
        WHEN COALESCE(u.usename, r.rolname) LIKE '%customer%' OR COALESCE(u.usename, r.rolname) LIKE '%service%' THEN 'Customer Service'
        WHEN COALESCE(u.usename, r.rolname) LIKE '%finance%' THEN 'Finance Team'
        WHEN COALESCE(u.usename, r.rolname) LIKE '%product%' THEN 'Product Management'
        WHEN COALESCE(u.usename, r.rolname) LIKE '%security%' OR COALESCE(u.usename, r.rolname) LIKE '%audit%' THEN 'Security Team'
        WHEN COALESCE(u.usename, r.rolname) LIKE '%backup%' THEN 'Backup Service'
        WHEN COALESCE(u.usename, r.rolname) LIKE '%developer%' OR COALESCE(u.usename, r.rolname) LIKE '%dev%' THEN 'Development Team'
        WHEN COALESCE(u.usename, r.rolname) LIKE '%temp%' OR COALESCE(u.usename, r.rolname) LIKE '%old%' OR COALESCE(u.usename, r.rolname) LIKE '%test%' THEN 'Inactive/Temporary'
        ELSE 'Unknown'
    END as inferred_business_role
FROM pg_user u
FULL OUTER JOIN pg_roles r ON u.usename = r.rolname
WHERE COALESCE(u.usename, r.rolname) NOT IN ('postgres', 'test_user')
AND COALESCE(u.usename, r.rolname) IS NOT NULL;

-- ============================================================================
-- DISCOVER ROLE MEMBERSHIPS
-- ============================================================================

CREATE TEMP TABLE temp_role_memberships AS
SELECT 
    member_role.rolname as member_name,
    granted_role.rolname as granted_role_name,
    grantor_role.rolname as grantor_name,
    am.admin_option
FROM pg_auth_members am
JOIN pg_roles member_role ON am.member = member_role.oid
JOIN pg_roles granted_role ON am.roleid = granted_role.oid  
JOIN pg_roles grantor_role ON am.grantor = grantor_role.oid
WHERE member_role.rolname NOT IN ('postgres')
AND granted_role.rolname NOT IN ('postgres');

-- ============================================================================
-- ANALYZE CURRENT PERMISSIONS
-- ============================================================================

CREATE TEMP TABLE temp_current_permissions AS
SELECT DISTINCT
    tp.grantee as username,
    tp.table_name,
    tp.privilege_type as permission_type,
    tp.is_grantable,
    tp.grantor,
    ud.inferred_business_role,
    ud.is_superuser
FROM information_schema.table_privileges tp
LEFT JOIN temp_user_discovery ud ON tp.grantee = ud.username
WHERE tp.table_schema = 'public'
AND tp.grantee NOT IN ('postgres', 'PUBLIC', 'test_user')
AND tp.table_name NOT LIKE 'security_audit_%'
ORDER BY tp.grantee, tp.table_name, tp.privilege_type;

-- ============================================================================
-- IDENTIFY DANGLING USERS
-- ============================================================================

INSERT INTO security_audit_details (username, issue_type, table_name, permission_type, expected_access)
SELECT DISTINCT
    username,
    'DANGLING_USER',
    NULL,
    NULL,
    FALSE
FROM temp_user_discovery
WHERE inferred_business_role = 'Inactive/Temporary';

-- ============================================================================
-- IDENTIFY EXCESSIVE PERMISSIONS
-- ============================================================================

WITH excessive_permissions AS (
    SELECT username, table_name, permission_type FROM (VALUES
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
    ) AS excessive(username, table_name, permission_type)
)
INSERT INTO security_audit_details (username, issue_type, table_name, permission_type, expected_access)
SELECT 
    ep.username,
    'EXCESSIVE_PERMISSION',
    ep.table_name,
    ep.permission_type,
    FALSE
FROM excessive_permissions ep
WHERE EXISTS (
    SELECT 1 FROM temp_current_permissions cp
    WHERE cp.username = ep.username
    AND cp.table_name = ep.table_name  
    AND cp.permission_type = ep.permission_type
);

-- ============================================================================
-- IDENTIFY MISSING PERMISSIONS
-- ============================================================================

WITH expected_permissions AS (
    SELECT role_name, table_name, permission_type FROM (VALUES
        ('Analytics Team', 'user_profiles', 'SELECT'),
        ('Analytics Team', 'user_stat_analysis', 'SELECT'),
        ('Analytics Team', 'product_catalog', 'SELECT'),
        ('Analytics Team', 'order_management', 'SELECT'),
        ('Marketing Department', 'user_profiles', 'SELECT'),
        ('Marketing Department', 'user_stat_analysis', 'SELECT'),
        ('Marketing Department', 'product_catalog', 'SELECT'),
        ('Customer Service', 'user_profiles', 'SELECT'),
        ('Customer Service', 'user_profiles', 'UPDATE'),
        ('Customer Service', 'order_management', 'SELECT'),
        ('Customer Service', 'order_management', 'INSERT'),
        ('Customer Service', 'order_management', 'UPDATE'),
        ('Customer Service', 'product_catalog', 'SELECT'),
        ('Finance Team', 'financial_transactions', 'SELECT'),
        ('Finance Team', 'order_management', 'SELECT'),
        ('Finance Team', 'user_profiles', 'SELECT'),
        ('Product Management', 'product_catalog', 'SELECT'),
        ('Product Management', 'product_catalog', 'INSERT'),
        ('Product Management', 'product_catalog', 'UPDATE'),
        ('Product Management', 'product_catalog', 'DELETE'),
        ('Product Management', 'order_management', 'SELECT'),
        ('Product Management', 'user_stat_analysis', 'SELECT'),
        ('Security Team', 'audit_logs', 'SELECT'),
        ('Security Team', 'user_credentials', 'SELECT'),
        ('Security Team', 'user_profiles', 'SELECT'),
        ('Development Team', 'user_profiles', 'SELECT'),
        ('Development Team', 'product_catalog', 'SELECT'),
        ('Backup Service', 'user_profiles', 'SELECT'),
        ('Backup Service', 'product_catalog', 'SELECT'),
        ('Backup Service', 'order_management', 'SELECT'),
        ('Backup Service', 'financial_transactions', 'SELECT'),
        ('Backup Service', 'user_stat_analysis', 'SELECT'),
        ('Backup Service', 'audit_logs', 'SELECT'),
        ('Backup Service', 'user_credentials', 'SELECT')
    ) AS expected(role_name, table_name, permission_type)
)
INSERT INTO security_audit_details (username, issue_type, table_name, permission_type, expected_access)
SELECT DISTINCT
    ud.username,
    'MISSING_PERMISSION',
    ep.table_name,
    ep.permission_type,
    TRUE
FROM temp_user_discovery ud
JOIN expected_permissions ep ON ud.inferred_business_role = ep.role_name
LEFT JOIN temp_current_permissions cp ON (
    cp.username = ud.username 
    AND cp.table_name = ep.table_name 
    AND cp.permission_type = ep.permission_type
)
WHERE cp.username IS NULL
AND ud.inferred_business_role != 'Inactive/Temporary'
AND ud.inferred_business_role != 'Unknown'
AND EXISTS (
    SELECT 1 FROM information_schema.tables t
    WHERE t.table_name = ep.table_name 
    AND t.table_schema = 'public'
    AND t.table_type = 'BASE TABLE'
);

-- ============================================================================
-- POPULATE SUMMARY STATISTICS
-- ============================================================================

INSERT INTO security_audit_results (audit_type, total_issues, users_affected, tables_affected)
SELECT 
    'DANGLING_USERS',
    COUNT(*),
    COUNT(DISTINCT username),
    0
FROM security_audit_details
WHERE issue_type = 'DANGLING_USER';

INSERT INTO security_audit_results (audit_type, total_issues, users_affected, tables_affected)
SELECT 
    'MISSING_PERMISSIONS',
    COUNT(*),
    COUNT(DISTINCT username),
    COUNT(DISTINCT table_name)
FROM security_audit_details
WHERE issue_type = 'MISSING_PERMISSION';

INSERT INTO security_audit_results (audit_type, total_issues, users_affected, tables_affected)
SELECT 
    'EXCESSIVE_PERMISSIONS',
    COUNT(*),
    COUNT(DISTINCT username),
    COUNT(DISTINCT table_name)
FROM security_audit_details
WHERE issue_type = 'EXCESSIVE_PERMISSION';

-- ============================================================================
-- CLEANUP TEMPORARY TABLES
-- ============================================================================

DROP TABLE temp_user_discovery;
DROP TABLE temp_role_memberships;
DROP TABLE temp_current_permissions;

COMMIT;

-- ============================================================================
-- DISCOVERY AND VERIFICATION QUERIES
-- ============================================================================

-- Show all users and their properties
SELECT 
    usename as username,
    usesuper as is_superuser,
    usecreatedb as can_create_db,
    valuntil as password_expiry
FROM pg_user 
WHERE usename NOT IN ('postgres', 'test_user')
ORDER BY usename;

-- Show all roles and their properties  
SELECT 
    rolname as role_name,
    rolsuper as is_superuser,
    rolinherit as inherits_privileges,
    rolcanlogin as can_login
FROM pg_roles 
WHERE rolname NOT LIKE 'pg_%'
AND rolname NOT IN ('postgres', 'test_user')
ORDER BY rolname;

-- Show current table privileges
SELECT 
    grantee as username,
    table_name,
    privilege_type as permission,
    is_grantable
FROM information_schema.table_privileges
WHERE table_schema = 'public'
AND grantee NOT IN ('postgres', 'PUBLIC', 'test_user')
AND table_name NOT LIKE 'security_audit_%'
ORDER BY grantee, table_name, privilege_type;

-- Show role memberships
SELECT 
    member.rolname as member,
    granted.rolname as granted_role
FROM pg_auth_members am
JOIN pg_roles member ON am.member = member.oid
JOIN pg_roles granted ON am.roleid = granted.oid
WHERE member.rolname NOT IN ('postgres')
ORDER BY member.rolname, granted.rolname;

-- Display audit summary
SELECT 
    audit_type,
    total_issues,
    users_affected,
    tables_affected
FROM security_audit_results 
ORDER BY audit_type;

-- Display detailed findings
SELECT 
    username,
    issue_type,
    COALESCE(table_name, 'N/A') as table_name,
    COALESCE(permission_type, 'N/A') as permission_type,
    expected_access
FROM security_audit_details 
ORDER BY issue_type, username, table_name;