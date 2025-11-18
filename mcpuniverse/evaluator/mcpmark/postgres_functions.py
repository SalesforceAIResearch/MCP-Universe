"""
Custom evaluator functions for MCPMark Postgres tasks.

These functions adapt verification logic from postgres task verify.py files
into the MCP-Universe evaluator framework.

Argument conventions (per Evaluator.evaluate):
- compare_fn(x, value, op_args, context=...) is invoked as:
  - x: result from func-chain (first positional arg)
  - value: config.value (args[0])
  - op_args: config.op_args (args[1])
  - context: keyword-only in kwargs
"""
# pylint: disable=line-too-long,import-outside-toplevel,duplicate-code

from __future__ import annotations

from typing import Tuple
from mcpuniverse.evaluator.functions import compare_func


##################################################################################
# Chinook - Customer Data Migration
##################################################################################

@compare_func(name="postgres_customer_data_migration_verifier")
async def postgres_customer_data_migration_verifier(_x: dict, *_args, **_kwargs) -> Tuple[bool, str]:
    """
    Verify the Customer Data Migration task.

    Adapted from: mcpuniverse/evaluator/mcpmark/postgres/chinook/customer_data_migration/verify.py

    Checks:
    - All customer records from MelodyMart are migrated
    - Customer IDs start from next available ID
    - All customers assigned to support representative with EmployeeId 3
    - Fax field set to NULL for all migrated customers
    - Customer data matches expected values
    """
    from mcpuniverse.evaluator.mcpmark.postgres.chinook.customer_data_migration.verify import verify

    # Call the verify function
    passed, error_msg = verify()
    return passed, error_msg


##################################################################################
# Chinook - Employee Hierarchy Management
##################################################################################

@compare_func(name="postgres_employee_hierarchy_verifier")
async def postgres_employee_hierarchy_verifier(_x: dict, *_args, **_kwargs) -> Tuple[bool, str]:
    """
    Verify the Employee Hierarchy Management task.

    Adapted from: mcpuniverse/evaluator/mcpmark/postgres/chinook/employee_hierarchy_management/verify.py

    Checks:
    - Employee count and title changes are correct
    - Specific employee records match expected values
    - Customer assignments to new employees are correct
    - Employee performance table exists with correct data
    - Robert King is deleted
    - Laura Callahan is promoted to Senior IT Specialist
    - Salary column exists with correct values
    """
    from mcpuniverse.evaluator.mcpmark.postgres.chinook.employee_hierarchy_management.verify import verify

    # Call the verify function
    passed, error_msg = verify()
    return passed, error_msg


##################################################################################
# Chinook - Sales and Music Charts
##################################################################################

@compare_func(name="postgres_sales_music_charts_verifier")
async def postgres_sales_music_charts_verifier(_x: dict, *_args, **_kwargs) -> Tuple[bool, str]:
    """
    Verify the Sales and Music Charts task.

    Adapted from: mcpuniverse/evaluator/mcpmark/postgres/chinook/sales_and_music_charts/verify.py

    Checks:
    - monthly_sales_summary table exists with correct data
    - Monthly sales metrics are calculated correctly
    - top_music_charts table exists with correct data
    - Top 10 tracks, albums, and artists are ranked correctly
    - Revenue calculations are accurate
    """
    from mcpuniverse.evaluator.mcpmark.postgres.chinook.sales_and_music_charts.verify import verify

    # Call the verify function
    passed, error_msg = verify()
    return passed, error_msg


##################################################################################
# DVDRental - Customer Analysis Fix
##################################################################################

@compare_func(name="postgres_customer_analysis_fix_verifier")
async def postgres_customer_analysis_fix_verifier(_x: dict, *_args, **_kwargs) -> Tuple[bool, str]:
    """
    Verify the Customer Analysis Query Fix task.

    Adapted from: mcpuniverse/evaluator/mcpmark/postgres/dvdrental/customer_analysis_fix/verify.py

    Checks:
    - customer_analysis_fixed table exists with correct data
    - Query correctly handles duplicate counting
    - Only paid rentals are counted
    - Only customers with at least 15 rentals are included
    - Only customers with valid email addresses are included
    - All 587 rows match expected results
    """
    from mcpuniverse.evaluator.mcpmark.postgres.dvdrental.customer_analysis_fix.verify import verify

    # Call the verify function
    passed, error_msg = verify()
    return passed, error_msg


##################################################################################
# DVDRental - Customer Analytics Optimization
##################################################################################

@compare_func(name="postgres_customer_analytics_optimization_verifier")
async def postgres_customer_analytics_optimization_verifier(_x: dict, *_args, **_kwargs) -> Tuple[bool, str]:
    """
    Verify the Customer Analytics Query Optimization task.

    Adapted from: mcpuniverse/evaluator/mcpmark/postgres/dvdrental/customer_analytics_optimization/verify.py

    Checks:
    - Index exists on payment.customer_id column
    - Query performance is optimized
    """
    from mcpuniverse.evaluator.mcpmark.postgres.dvdrental.customer_analytics_optimization.verify import verify

    # Call the verify function
    passed, error_msg = verify()
    return passed, error_msg


##################################################################################
# DVDRental - Film Inventory Management
##################################################################################

@compare_func(name="postgres_film_inventory_verifier")
async def postgres_film_inventory_verifier(_x: dict, *_args, **_kwargs) -> Tuple[bool, str]:
    """
    Verify the Film Inventory Management task.

    Adapted from: mcpuniverse/evaluator/mcpmark/postgres/dvdrental/film_inventory_management/verify.py

    Checks:
    - New films added correctly
    - Inventory records added for new films
    - Film rental rates updated for PG-13 rated films
    - available_films table created and populated correctly
    - Inventory cleanup performed correctly
    - film_inventory_summary table created and populated correctly
    """
    from mcpuniverse.evaluator.mcpmark.postgres.dvdrental.film_inventory_management.verify import verify

    # Call the verify function
    passed, error_msg = verify()
    return passed, error_msg


##################################################################################
# Employees - Demographics Report
##################################################################################

@compare_func(name="postgres_employee_demographics_verifier")
async def postgres_employee_demographics_verifier(_x: dict, *_args, **_kwargs) -> Tuple[bool, str]:
    """
    Verify the Employee Demographics Report task.

    Adapted from: mcpuniverse/evaluator/mcpmark/postgres/employees/employee_demographics_report/verify.py

    Checks:
    - gender_statistics table with correct data
    - age_group_analysis table with correct statistics
    - birth_month_distribution table with employee counts
    - hiring_year_summary table with retention rates
    """
    from mcpuniverse.evaluator.mcpmark.postgres.employees.employee_demographics_report.verify import verify

    # Call the verify function
    passed, error_msg = verify()
    return passed, error_msg


##################################################################################
# Employees - Performance Analysis
##################################################################################

@compare_func(name="postgres_employee_performance_verifier")
async def postgres_employee_performance_verifier(_x: dict, *_args, **_kwargs) -> Tuple[bool, str]:
    """
    Verify the Employee Performance Analysis task.

    Adapted from: mcpuniverse/evaluator/mcpmark/postgres/employees/employee_performance_analysis/verify.py

    Checks:
    - employee_performance_analysis table with performance categories
    - Salary growth rate calculations
    - Promotion count tracking
    - department_salary_analysis table with salary metrics
    """
    from mcpuniverse.evaluator.mcpmark.postgres.employees.employee_performance_analysis.verify import verify

    # Call the verify function
    passed, error_msg = verify()
    return passed, error_msg


##################################################################################
# Employees - Project Tracking
##################################################################################

@compare_func(name="postgres_employee_project_tracking_verifier")
async def postgres_employee_project_tracking_verifier(_x: dict, *_args, **_kwargs) -> Tuple[bool, str]:
    """
    Verify the Employee Project Tracking task.

    Adapted from: mcpuniverse/evaluator/mcpmark/postgres/employees/employee_project_tracking/verify.py

    Checks:
    - Three project tracking tables created with correct structure
    - Foreign key constraints exist
    - Indexes created correctly
    - Project data inserted and updated
    - Employee assignments by department
    - Milestone data with completion status
    """
    from mcpuniverse.evaluator.mcpmark.postgres.employees.employee_project_tracking.verify import verify

    # Call the verify function
    passed, error_msg = verify()
    return passed, error_msg


##################################################################################
# Employees - Retention Analysis
##################################################################################

@compare_func(name="postgres_employee_retention_verifier")
async def postgres_employee_retention_verifier(_x: dict, *_args, **_kwargs) -> Tuple[bool, str]:
    """
    Verify the Employee Retention Analysis task.

    Adapted from: mcpuniverse/evaluator/mcpmark/postgres/employees/employee_retention_analysis/verify.py

    Checks:
    - employee_retention_analysis table with retention rates by department
    - high_risk_employees table with risk categorization
    - turnover_trend_analysis table with historical departure data
    """
    from mcpuniverse.evaluator.mcpmark.postgres.employees.employee_retention_analysis.verify import verify

    # Call the verify function
    passed, error_msg = verify()
    return passed, error_msg


##################################################################################
# Employees - Executive Dashboard Automation
##################################################################################

@compare_func(name="postgres_executive_dashboard_automation_verifier")
async def postgres_executive_dashboard_automation_verifier(_x: dict, *_args, **_kwargs) -> Tuple[bool, str]:
    """
    Verify the Executive Dashboard Automation task.

    Adapted from: mcpuniverse/evaluator/mcpmark/postgres/employees/executive_dashboard_automation/verify.py

    Checks:
    - exec_department_summary materialized view
    - exec_hiring_trends materialized view
    - exec_salary_distribution materialized view
    - All views contain correct aggregated data
    """
    from mcpuniverse.evaluator.mcpmark.postgres.employees.executive_dashboard_automation.verify import verify

    # Call the verify function
    passed, error_msg = verify()
    return passed, error_msg


##################################################################################
# Employees - Management Structure Analysis
##################################################################################

@compare_func(name="postgres_management_structure_analysis_verifier")
async def postgres_management_structure_analysis_verifier(_x: dict, *_args, **_kwargs) -> Tuple[bool, str]:
    """
    Verify the Management Structure Analysis task.

    Adapted from: mcpuniverse/evaluator/mcpmark/postgres/employees/management_structure_analysis/verify.py

    Checks:
    - manager_profile table with management history
    - department_leadership table with current managers
    - management_transitions table with historical changes
    - span_of_control table with team size metrics
    """
    from mcpuniverse.evaluator.mcpmark.postgres.employees.management_structure_analysis.verify import verify

    # Call the verify function
    passed, error_msg = verify()
    return passed, error_msg


##################################################################################
# LEGO - Consistency Enforcement
##################################################################################

@compare_func(name="postgres_consistency_enforcement_verifier")
async def postgres_consistency_enforcement_verifier(_x: dict, *_args, **_kwargs) -> Tuple[bool, str]:
    """
    Verify the LEGO Consistency Enforcement task.

    Adapted from: mcpuniverse/evaluator/mcpmark/postgres/lego/consistency_enforcement/verify.py

    Checks:
    - Data consistency between lego_sets.num_parts and inventory parts
    - Constraint triggers exist on all required tables
    - Triggers block inconsistent writes
    - Deferred constraints allow coordinated updates
    """
    from mcpuniverse.evaluator.mcpmark.postgres.lego.consistency_enforcement.verify import verify

    # Call the verify function
    passed, error_msg = verify()
    return passed, error_msg


##################################################################################
# LEGO - Database Security Policies
##################################################################################

@compare_func(name="postgres_database_security_policies_verifier")
async def postgres_database_security_policies_verifier(_x: dict, *_args, **_kwargs) -> Tuple[bool, str]:
    """
    Verify the LEGO Database Security Policies task.

    Adapted from: mcpuniverse/evaluator/mcpmark/postgres/lego/database_security_policies/verify.py

    Checks:
    - theme_analyst role created with correct permissions
    - Row-Level Security enabled on required tables
    - RLS policies created for theme-based data isolation
    - get_user_theme_id() function works correctly
    - Theme-based access control functions as expected
    """
    from mcpuniverse.evaluator.mcpmark.postgres.lego.database_security_policies.verify import verify

    # Call the verify function
    passed, error_msg = verify()
    return passed, error_msg


##################################################################################
# LEGO - Transactional Inventory Transfer
##################################################################################

@compare_func(name="postgres_transactional_inventory_transfer_verifier")
async def postgres_transactional_inventory_transfer_verifier(_x: dict, *_args, **_kwargs) -> Tuple[bool, str]:
    """
    Verify the LEGO Transactional Inventory Transfer task.

    Adapted from: mcpuniverse/evaluator/mcpmark/postgres/lego/transactional_inventory_transfer/verify.py

    Checks:
    - transfer_parts function exists
    - inventory_transfer_log audit table exists
    - Successful transfers with audit logging
    - New part transfers to inventories
    - Business rule validation (self-transfer, quantity limits)
    - Insufficient quantity error handling
    - Invalid inventory error handling
    - Audit logging for success and failure cases
    - Exact quantity transfers (source row deletion)
    """
    from mcpuniverse.evaluator.mcpmark.postgres.lego.transactional_inventory_transfer.verify import verify

    # Call the verify function
    passed, error_msg = verify()
    return passed, error_msg


##################################################################################
# Security - RLS Business Access
##################################################################################

@compare_func(name="postgres_rls_business_access_verifier")
async def postgres_rls_business_access_verifier(_x: dict, *_args, **_kwargs) -> Tuple[bool, str]:
    """
    Verify the RLS Business Access task for social media platform.

    Adapted from: mcpuniverse/evaluator/mcpmark/postgres/security/rls_business_access/verify.py

    Checks:
    - RLS enabled on all required tables (users, channels, posts, comments)
    - Users can only update their own profile
    - Channel owners can update their channels
    - Post authorship and moderation controls work correctly
    - Comment access controls work correctly
    - Moderator assignment controls work correctly
    - Content visibility based on user context
    - Anonymous user access restrictions
    """
    from mcpuniverse.evaluator.mcpmark.postgres.security.rls_business_access.verify import verify

    # Call the verify function
    passed, error_msg = verify()
    return passed, error_msg


##################################################################################
# Security - User Permission Audit
##################################################################################

@compare_func(name="postgres_security_verifier")
async def postgres_security_verifier(_x: dict, *_args, **_kwargs) -> Tuple[bool, str]:
    """
    Verify the User Permission Audit task for e-commerce database.

    Adapted from: mcpuniverse/evaluator/mcpmark/postgres/security/user_permission_audit/verify.py

    Checks:
    - security_audit_results table exists with correct summary data
    - security_audit_details table exists with all findings
    - Dangling users identified (3 expected)
    - Missing permissions identified (13 expected)
    - Excessive permissions identified (13 expected)
    - Audit summary contains correct counts
    """
    from mcpuniverse.evaluator.mcpmark.postgres.security.user_permission_audit.verify import verify

    # Call the verify function
    passed, error_msg = verify()
    return passed, error_msg


##################################################################################
# Sports - Baseball Player Analysis
##################################################################################

@compare_func(name="postgres_baseball_player_analysis_verifier")
async def postgres_baseball_player_analysis_verifier(_x: dict, *_args, **_kwargs) -> Tuple[bool, str]:
    """
    Verify the Baseball Player Analysis task.

    Adapted from: mcpuniverse/evaluator/mcpmark/postgres/sports/baseball_player_analysis/verify.py

    Checks:
    - baseball_player_analysis table created with correct structure
    - All qualifying players included (games >= 10, at_bats >= 50)
    - Offensive statistics calculated correctly
    - Defensive statistics calculated correctly
    - Batting average and fielding percentage formulas correct
    """
    from mcpuniverse.evaluator.mcpmark.postgres.sports.baseball_player_analysis.verify import verify

    # Call the verify function
    passed, error_msg = verify()
    return passed, error_msg


##################################################################################
# Sports - Participant Report Optimization
##################################################################################

@compare_func(name="postgres_participant_report_optimization_verifier")
async def postgres_participant_report_optimization_verifier(_x: dict, *_args, **_kwargs) -> Tuple[bool, str]:
    """
    Verify the Participant Report Optimization task.

    Adapted from: mcpuniverse/evaluator/mcpmark/postgres/sports/participant_report_optimization/verify.py

    Checks:
    - participant_performance_report table created and populated
    - Report data matches ground truth query results
    - Critical performance indexes created on participants_events and stats tables
    - Query optimization implemented correctly
    """
    from mcpuniverse.evaluator.mcpmark.postgres.sports.participant_report_optimization.verify import verify

    # Call the verify function
    passed, error_msg = verify()
    return passed, error_msg


##################################################################################
# Sports - Team Roster Management
##################################################################################

@compare_func(name="postgres_team_roster_management_verifier")
async def postgres_team_roster_management_verifier(_x: dict, *_args, **_kwargs) -> Tuple[bool, str]:
    """
    Verify the Team Roster Management task.

    Adapted from: mcpuniverse/evaluator/mcpmark/postgres/sports/team_roster_management/verify.py

    Checks:
    - player_evaluation table created with correct player data
    - Performance scores calculated correctly with injury adjustments
    - player_injury_status table created with injury tracking
    - team_performance_summary table created with aggregated metrics
    - All operations completed in correct order
    """
    from mcpuniverse.evaluator.mcpmark.postgres.sports.team_roster_management.verify import verify

    # Call the verify function
    passed, error_msg = verify()
    return passed, error_msg


##################################################################################
# Vectors - DBA Vector Analysis
##################################################################################

@compare_func(name="postgres_dba_vector_analysis_verifier")
async def postgres_dba_vector_analysis_verifier(_x: dict, *_args, **_kwargs) -> Tuple[bool, str]:
    """
    Verify the DBA Vector Analysis task.

    Adapted from: mcpuniverse/evaluator/mcpmark/postgres/vectors/dba_vector_analysis/verify.py

    Checks:
    - vector_analysis_columns table created with all vector columns identified
    - vector_analysis_storage_consumption table created with storage analysis
    - vector_analysis_indices table created with vector index information
    - No unexpected analysis tables exist
    - All vector tables, columns, and indexes properly analyzed
    """
    from mcpuniverse.evaluator.mcpmark.postgres.vectors.dba_vector_analysis.verify import verify

    # Call the verify function
    passed, error_msg = verify()
    return passed, error_msg
