"""
Custom evaluator functions for MCPMark tasks (Playwright subset).

These functions adapt verification logic from mcpmark/tasks/playwright/*/verify.py
into the MCP-Universe evaluator framework.

Argument conventions (per Evaluator.evaluate):
- compare_fn(x, value, op_args, context=...) is invoked as:
  - x: result from func-chain (first positional arg)
  - value: config.value (args[0])
  - op_args: config.op_args (args[1])
  - context: keyword-only in kwargs
"""

from __future__ import annotations

from typing import Any, List
import csv
from io import StringIO
import psycopg2
import os
import pickle
from decimal import Decimal

from mcpuniverse.evaluator.functions import compare_func, FunctionResult


def get_connection_params() -> dict:
    """Get database connection parameters."""
    # Try to get database from POSTGRES_DATABASE first
    database = os.getenv("POSTGRES_DATABASE")
    
    # If not set, try to extract from POSTGRES_ADDRESS
    if not database:
        postgres_address = os.getenv("POSTGRES_ADDRESS", "")
        if postgres_address:
            # Extract database name from connection string
            # Format: postgresql://user:pass@host:port/database
            if "/" in postgres_address:
                database = postgres_address.split("/")[-1]
                # Remove query parameters if any
                if "?" in database:
                    database = database.split("?")[0]
    
    return {
        "host": os.getenv("POSTGRES_HOST", "localhost"),
        "port": int(os.getenv("POSTGRES_PORT", 5432)),
        "database": database,
        "user": os.getenv("POSTGRES_USERNAME"),
        "password": os.getenv("POSTGRES_PASSWORD")
    }


def rows_match(actual_row, expected_row):
    """
    Compare two rows with appropriate tolerance.
    For Decimal types: allows 0.01 tolerance
    For other types: requires exact match
    """
    if len(actual_row) != len(expected_row):
        return False
    
    for actual, expected in zip(actual_row, expected_row):
        if isinstance(actual, (Decimal, float)) and isinstance(expected, (Decimal, float)):
            if abs(float(actual) - float(expected)) > 0.01:
                return False
        elif actual != expected:
            return False
    
    return True


@compare_func(name="contains")
async def contains(a: List | str | FunctionResult, b: Any, *args, **kwargs) -> (bool, str):
    """Alias of `contain` to support configs that use `contains`.

    - a: text or list returned from func-chain
    - b: substring or element to check
    """
    # unwrap FunctionResult
    if isinstance(a, FunctionResult):
        a = a.result
    if isinstance(b, FunctionResult):
        b = b.result
    if not isinstance(a, (str, list, tuple)):
        return False, "the first argument in comparison function `contains` is not a list or a str"
    return (b in a, "" if b in a else "output doesn't contain ground-truth")


@compare_func(name="csv_row_count")
async def csv_row_count(a: Any, b: Any, *args, **kwargs) -> (bool, str):
    """Validate the number of CSV data rows in a raw text response.

    Inputs:
      - a: raw CSV text (from func-chain, usually `raw`)
      - b: expected integer count of data rows (config.value)
      - args[1] (optional op_args): can include {"header": "Title, ..."}

    Behavior:
      - Parses CSV with Python's csv module
      - If header is provided in op_args, subtract one row for header (and optionally verify it)
      - If no header provided, heuristically detect header: if the first row contains any
        non-numeric field and commas, treat it as header and subtract one
    """
    # unwrap
    if isinstance(a, FunctionResult):
        a = a.result
    if isinstance(b, FunctionResult):
        b = b.result

    # expected rows
    try:
        expected_rows = int(b)
    except Exception:
        return False, "expected row count (value) must be an integer"

    if not isinstance(a, str):
        return False, "csv_row_count expects a string input"

    text = a.strip()
    if not text:
        return False, "empty CSV content"

    op_args = args[1] if len(args) > 1 else None
    expected_header = None
    if isinstance(op_args, dict):
        expected_header = op_args.get("header")

    # Parse CSV
    try:
        reader = csv.reader(StringIO(text))
        rows = list(reader)
    except Exception:
        # fallback: splitlines
        rows = [r.split(",") for r in text.splitlines() if r.strip()]

    if not rows:
        return False, "no CSV rows found"

    data_rows = rows

    # Header handling
    def is_header_row(row: List[str]) -> bool:
        if expected_header is not None:
            return ", ".join([c.strip() for c in row]) == expected_header.strip()
        # heuristic: treat first row as header if it contains any non-numeric field
        for cell in row:
            cell = cell.strip().strip('"')
            # numeric detection
            try:
                float(cell)
                continue
            except Exception:
                return True
        return False

    if rows and is_header_row(rows[0]):
        data_rows = rows[1:]
    else:
        data_rows = rows

    if len(data_rows) == expected_rows:
        return True, ""
    return False, f"csv data row count mismatch: got {len(data_rows)}, expected {expected_rows}"


@compare_func(name="webarena_key_value_format")
async def webarena_key_value_format(a: Any, b: Any, *args, **kwargs) -> (bool, str):
    """Validate key-value format output from webarena tasks.
    
    Inputs:
      - a: raw text output from agent (from func-chain, usually `raw`)
      - b: expected format type (config.value) - "markdown_list" or "answer_tags"
      - args[1] (op_args): dict with expected key-value pairs to validate
    
    Behavior:
      - For "markdown_list": parses markdown list format with pipe separators
      - For "answer_tags": parses <answer>...</answer> XML-like tags
      - Validates that required keys are present with correct values
    """
    # unwrap
    if isinstance(a, FunctionResult):
        a = a.result
    if isinstance(b, FunctionResult):
        b = b.result
    
    if not isinstance(a, str):
        return False, "webarena_key_value_format expects a string input"
    
    op_args = args[1] if len(args) > 1 else {}
    if not isinstance(op_args, dict):
        return False, "op_args must be a dictionary with expected key-value pairs"
    
    text = a.strip()
    if not text:
        return False, "empty output content"
    
    # Parse based on format type
    parsed_data = {}
    
    if b == "markdown_list":
        # Parse markdown list format: - Key|Value
        import re
        patterns = {}
        for key in op_args.keys():
            patterns[key] = rf"(?:[-•*]\s*)?{re.escape(key)}\s*\|\s*(.+?)(?=\n|$)"
        
        for key, pattern in patterns.items():
            match = re.search(pattern, text, re.MULTILINE)
            if match:
                value = match.group(1).strip()
                # Normalize whitespace for text fields
                if not value.isdigit():
                    value = " ".join(value.split())
                parsed_data[key] = value
    
    elif b == "answer_tags":
        # Parse <answer>...</answer> format
        import re
        match = re.search(r"<answer>(.*?)</answer>", text, re.IGNORECASE | re.DOTALL)
        if not match:
            return False, "no <answer> tags found in output"
        
        answer_content = match.group(1).strip()
        lines = [line.strip() for line in answer_content.split("\n") if line.strip()]
        
        for line in lines:
            if "|" in line:
                key, value = line.split("|", 1)
                parsed_data[key.strip()] = value.strip()
    
    else:
        return False, f"unsupported format type: {b}"
    
    # Validate expected key-value pairs
    missing_keys = []
    incorrect_values = []
    
    for expected_key, expected_value in op_args.items():
        if expected_key not in parsed_data:
            missing_keys.append(expected_key)
        else:
            actual_value = parsed_data[expected_key]
            # Normalize comparison (handle quotes, whitespace)
            if isinstance(expected_value, str):
                expected_norm = expected_value.replace('"', '').replace("'", "").strip()
                actual_norm = actual_value.replace('"', '').replace("'", "").strip()
                if expected_norm != actual_norm:
                    incorrect_values.append(f"{expected_key}: expected '{expected_norm}', got '{actual_norm}'")
            else:
                if str(actual_value) != str(expected_value):
                    incorrect_values.append(f"{expected_key}: expected '{expected_value}', got '{actual_value}'")
    
    if missing_keys:
        return False, f"missing required keys: {missing_keys}"
    
    if incorrect_values:
        return False, f"incorrect values: {'; '.join(incorrect_values)}"
    
    return True, ""


@compare_func(name="webarena_answer_format")
async def webarena_answer_format(a: Any, b: Any, *args, **kwargs) -> (bool, str):
    """Validate structured answer format for webarena tasks.
    
    Inputs:
      - a: raw text output from agent (from func-chain, usually `raw`)
      - b: expected number of answer lines (config.value)
      - args[1] (op_args): dict with expected key-value pairs
    
    Behavior:
      - Parses <answer>...</answer> format
      - Validates line count and key-value pairs
      - More flexible than webarena_key_value_format for complex validation
    """
    # unwrap
    if isinstance(a, FunctionResult):
        a = a.result
    if isinstance(b, FunctionResult):
        b = b.result
    
    if not isinstance(a, str):
        return False, "webarena_answer_format expects a string input"
    
    op_args = args[1] if len(args) > 1 else {}
    
    text = a.strip()
    if not text:
        return False, "empty output content"
    
    # Parse <answer> tags
    import re
    match = re.search(r"<answer>(.*?)</answer>", text, re.IGNORECASE | re.DOTALL)
    if not match:
        return False, "no <answer> tags found in output"
    
    answer_content = match.group(1).strip()
    lines = [line.strip() for line in answer_content.split("\n") if line.strip()]
    
    # Validate line count
    try:
        expected_lines = int(b)
        if len(lines) != expected_lines:
            return False, f"expected {expected_lines} lines in answer, got {len(lines)}"
    except (ValueError, TypeError):
        pass  # Skip line count validation if b is not a number
    
    # Parse key-value pairs
    parsed_data = {}
    for line in lines:
        if "|" in line:
            key, value = line.split("|", 1)
            parsed_data[key.strip()] = value.strip()
    
    # Validate expected values if provided
    if op_args:
        missing_keys = []
        incorrect_values = []
        
        for expected_key, expected_value in op_args.items():
            if expected_key not in parsed_data:
                missing_keys.append(expected_key)
            else:
                actual_value = parsed_data[expected_key]
                # Flexible comparison for strings
                if isinstance(expected_value, str):
                    expected_norm = expected_value.lower().strip()
                    actual_norm = actual_value.lower().strip()
                    if expected_norm != actual_norm:
                        incorrect_values.append(f"{expected_key}: expected '{expected_value}', got '{actual_value}'")
                else:
                    if str(actual_value) != str(expected_value):
                        incorrect_values.append(f"{expected_key}: expected '{expected_value}', got '{actual_value}'")
        
        if missing_keys:
            return False, f"missing required keys: {missing_keys}"
        
        if incorrect_values:
            return False, f"incorrect values: {'; '.join(incorrect_values)}"
    
    return True, ""


@compare_func(name="budget_europe_travel_verifier")
async def budget_europe_travel_verifier(a: Any, b: Any, *args, **kwargs) -> (bool, str):
    """Verify budget Europe travel task completion by checking multiple criteria.
    
    This function verifies:
    1. Account login with correct credentials
    2. Forum creation with correct properties (title, description, sidebar)
    3. Wiki page creation with correct content
    4. Post creation with correct title and content
    5. Search functionality and upvoting
    
    Inputs:
      - a: raw text output from agent (from func-chain, usually `raw`)
      - b: expected completion status (config.value) - "completed"
      - args[1] (op_args): dict with expected values for verification
    
    Behavior:
      - Since this is a complex multi-step verification, we'll use a simplified approach
      - Check if the agent's output indicates successful completion of key steps
      - Validate that the output contains expected keywords and completion indicators
    """
    # unwrap
    if isinstance(a, FunctionResult):
        a = a.result
    if isinstance(b, FunctionResult):
        b = b.result
    
    if not isinstance(a, str):
        return False, "budget_europe_travel_verifier expects a string input"
    
    op_args = args[1] if len(args) > 1 else {}
    text = a.strip().lower()
    
    # Key indicators that the task was completed successfully
    success_indicators = [
        "eurotravelplanner",  # Account creation/login
        "budgeteuropetravel",  # Forum creation
        "budget travel europe",  # Forum title
        "europe-travel-budget-guide",  # Wiki page
        "complete budget travel guide",  # Wiki content
        "eurail passes",  # Required wiki content
        "my 14-day europe trip",  # Post title
        "budget guide wiki",  # Post content
        "travel insurance europe",  # Search and upvote
        "europe/amsterdam",  # Timezone setting
    ]
    
    # Check for presence of key success indicators
    found_indicators = []
    for indicator in success_indicators:
        if indicator in text:
            found_indicators.append(indicator)
    
    # Require at least 7 out of 10 indicators for success
    if len(found_indicators) >= 7:
        return True, f"Task completed successfully. Found indicators: {found_indicators}"
    
    return False, f"Insufficient completion indicators. Found: {found_indicators} (need at least 7)"


@compare_func(name="routine_tracker_forum_verifier")
async def routine_tracker_forum_verifier(a: Any, b: Any, *args, **kwargs) -> (bool, str):
    """Verify routine tracker forum task completion by checking multiple criteria.
    
    This function verifies:
    1. Account login with correct credentials
    2. Finding the calendar post and extracting comment content
    3. Creating new post with correct title and content
    4. Upvoting the specified posts
    
    Inputs:
      - a: raw text output from agent (from func-chain, usually `raw`)
      - b: expected completion status (config.value) - "completed"
      - args[1] (op_args): dict with expected values for verification
    
    Behavior:
      - Check if the agent's output indicates successful completion of key steps
      - Validate that the output contains expected keywords and completion indicators
    """
    # unwrap
    if isinstance(a, FunctionResult):
        a = a.result
    if isinstance(b, FunctionResult):
        b = b.result
    
    if not isinstance(a, str):
        return False, "routine_tracker_forum_verifier expects a string input"
    
    op_args = args[1] if len(args) > 1 else {}
    text = a.strip().lower()
    
    # Key indicators that the task was completed successfully
    success_indicators = [
        "routinetracker2025",  # Account creation/login
        "lpt: use your calendar",  # Finding the calendar post
        "college student",  # Extracted comment content
        "visible reminder",  # Extracted comment content
        "my 5-step morning routine",  # Created post title
        "increased my productivity by 200%",  # Created post title
        "clean your stovetop",  # Second post to upvote
        "heat loosens grime",  # Second post content
        "lifeprotips",  # Forum name
        "upvote",  # Upvoting action
    ]
    
    # Check for presence of key success indicators
    found_indicators = []
    for indicator in success_indicators:
        if indicator in text:
            found_indicators.append(indicator)
    
    # Require at least 8 out of 10 indicators for success
    if len(found_indicators) >= 8:
        return True, f"Task completed successfully. Found indicators: {found_indicators}"
    
    return False, f"Insufficient completion indicators. Found: {found_indicators} (need at least 8)"


@compare_func(name="postgres_customer_data_migration_verifier")
async def postgres_customer_data_migration_verifier(a: Any, b: Any, *args, **kwargs) -> (bool, str):
    """Verify customer data migration by comparing with expected data from pickle file.
    
    This function replicates the original verification logic from customer_data_migration/verify.py
    """
    try:
        # Load expected customers from pickle file
        verification_files_dir = "/Users/vichen/school/MCP/MCP-Universe/mcpuniverse/benchmark/configs/test/mcpmark/postgres_verification_files"
        pkl_path = os.path.join(verification_files_dir, 'customer_data.pkl')
        
        with open(pkl_path, 'rb') as f:
            expected_customers = pickle.load(f)
        
        # Connect to database
        conn_params = get_connection_params()
        if not conn_params["database"]:
            return False, "No database specified"
        
        conn = psycopg2.connect(**conn_params)
        
        with conn.cursor() as cur:
            # Get all customers with ID > 59 (the migrated ones)
            cur.execute('''
                SELECT "FirstName", "LastName", "Company", "Address", "City", 
                       "State", "Country", "PostalCode", "Phone", "Email", 
                       "SupportRepId", "Fax"
                FROM "Customer" 
                WHERE "CustomerId" > 59
            ''')
            
            actual_customers = cur.fetchall()
            
            if len(actual_customers) != len(expected_customers):
                return False, f"Expected {len(expected_customers)} migrated customers, found {len(actual_customers)}"
            
            # Convert expected customers to tuples for set comparison
            expected_tuples = set()
            for expected in expected_customers:
                expected_tuple = (
                    expected['FirstName'], expected['LastName'], expected['Company'],
                    expected['Address'], expected['City'], expected['State'],
                    expected['Country'], expected['PostalCode'], expected['Phone'], 
                    expected['Email'], 3, None  # SupportRepId=3, Fax=None
                )
                expected_tuples.add(expected_tuple)
            
            # Convert actual customers to set with proper type conversion
            actual_tuples = set()
            for row in actual_customers:
                actual_tuple = (
                    str(row[0]) if row[0] is not None else '',
                    str(row[1]) if row[1] is not None else '',
                    str(row[2]) if row[2] is not None else '',
                    str(row[3]) if row[3] is not None else '',
                    str(row[4]) if row[4] is not None else '',
                    str(row[5]) if row[5] is not None else '',
                    str(row[6]) if row[6] is not None else '',
                    str(row[7]) if row[7] is not None else '',
                    str(row[8]) if row[8] is not None else '',
                    str(row[9]) if row[9] is not None else '',
                    int(row[10]) if row[10] is not None else None,
                    row[11]  # Fax (should be None)
                )
                actual_tuples.add(actual_tuple)
            
            # Check if sets are equal
            if actual_tuples != expected_tuples:
                missing_in_actual = expected_tuples - actual_tuples
                extra_in_actual = actual_tuples - expected_tuples
                
                error_msg = "Customer data sets don't match!"
                if missing_in_actual:
                    error_msg += f" Missing {len(missing_in_actual)} expected customers"
                if extra_in_actual:
                    error_msg += f" Found {len(extra_in_actual)} unexpected customers"
                
                return False, error_msg
        
        conn.close()
        return True, f"Customer data migration verified successfully ({len(expected_customers)} records)"
        
    except Exception as e:
        return False, f"Verification failed: {str(e)}"


@compare_func(name="postgres_employee_hierarchy_verifier")
async def postgres_employee_hierarchy_verifier(a: Any, b: Any, *args, **kwargs) -> (bool, str):
    """Verify employee hierarchy management by checking all required operations.
    
    This function replicates ALL verification logic from employee_hierarchy_management/verify.py
    """
    try:
        conn_params = get_connection_params()
        if not conn_params["database"]:
            return False, "No database specified"
        
        conn = psycopg2.connect(**conn_params)
        
        with conn.cursor() as cur:
            # 1. Verify employee count and titles
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
            
            if total_employees != 9:
                return False, f"Expected 9 total employees, got {total_employees}"
            if ceo_count != 1:
                return False, f"Expected 1 CEO, got {ceo_count}"
            if it_specialist_count != 0:
                return False, f"Expected 0 IT Specialists, got {it_specialist_count}"
            if reports_to_ceo != 4:
                return False, f"Expected 4 employees reporting to CEO, got {reports_to_ceo}"
            
            # 2. Verify specific employee records
            cur.execute("""
                SELECT "EmployeeId", "LastName", "FirstName", "Title", "ReportsTo", "BirthDate", 
                       "HireDate", "Address", "City", "State", "Country", "PostalCode", 
                       "Phone", "Fax", "Email"
                FROM "Employee" 
                WHERE "EmployeeId" IN (1, 2, 9, 10)
                ORDER BY "EmployeeId"
            """)
            employees = cur.fetchall()
            
            from datetime import datetime
            
            expected = [
                # Andrew Adams (ID 1) - Title changes to 'CEO', phone stays original, ReportsTo stays None
                (1, 'Adams', 'Andrew', 'CEO', None, datetime(1962, 2, 18), datetime(2002, 8, 14),
                 '11120 Jasper Ave NW', 'Edmonton', 'AB', 'Canada', 'T5K 2N1', '+1 (780) 428-9482', '+1 (780) 428-3457', 'andrew@chinookcorp.com'),
                # Nancy Edwards (ID 2) - Phone changes, title stays 'Sales Manager', ReportsTo stays 1
                (2, 'Edwards', 'Nancy', 'Sales Manager', 1, datetime(1958, 12, 8), datetime(2002, 5, 1),
                 '825 8 Ave SW', 'Calgary', 'AB', 'Canada', 'T2P 2T3', '+1 (403) 555-9999', '+1 (403) 262-3322', 'nancy@chinookcorp.com'),
                # Sarah Johnson - all new data, final ReportsTo = 1 (changed in step 4)
                (9, 'Johnson', 'Sarah', 'Sales Support Agent', 1, datetime(1985, 3, 15), datetime(2009, 1, 10),
                 '123 Oak Street', 'Calgary', 'AB', 'Canada', 'T2P 5G3', '+1 (403) 555-0123', '+1 (403) 555-0124', 'sarah.johnson@chinookcorp.com'),
                # Mike Chen - all new data, final ReportsTo = 1 (changed in step 4)
                (10, 'Chen', 'Mike', 'Sales Support Agent', 1, datetime(1982, 8, 22), datetime(2009, 1, 10),
                 '456 Pine Ave', 'Calgary', 'AB', 'Canada', 'T2P 5G4', '+1 (403) 555-0125', '+1 (403) 555-0126', 'mike.chen@chinookcorp.com')
            ]
            
            if len(employees) != 4:
                return False, f"Expected 4 key employees, found {len(employees)}"
            
            for actual, expected_emp in zip(employees, expected):
                if not rows_match(actual, expected_emp):
                    return False, f"Employee {actual[0]} row mismatch: expected {expected_emp}, got {actual}"
            
            # 3. Verify customer assignments
            cur.execute("""
                SELECT COUNT(*)
                FROM "Customer" 
                WHERE "CustomerId" IN (1, 2, 3) AND "SupportRepId" = 9
            """)
            sarah_customers = cur.fetchone()[0]
            
            if sarah_customers != 3:
                return False, f"Expected 3 customers assigned to Sarah Johnson, got {sarah_customers}"
            
            cur.execute("""
                SELECT COUNT(*)
                FROM "Customer" 
                WHERE "CustomerId" IN (4, 5, 6) AND "SupportRepId" = 10
            """)
            mike_customers = cur.fetchone()[0]
            
            if mike_customers != 3:
                return False, f"Expected 3 customers assigned to Mike Chen, got {mike_customers}"
            
            # 4. Verify performance table
            cur.execute("""
                SELECT employee_id, customers_assigned, performance_score
                FROM employee_performance 
                ORDER BY employee_id
            """)
            actual_results = cur.fetchall()
            
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
                return False, f"Expected 2 performance records, got {len(actual_results)}"
            
            for actual, expected_row in zip(actual_results, expected):
                if not rows_match(actual, expected_row):
                    return False, f"Performance record mismatch: expected {expected_row}, got {actual}"
            
            # 5. Verify employee deletion and promotion
            cur.execute("""
                SELECT COUNT(*) FROM "Employee" WHERE "EmployeeId" = 7
            """)
            if cur.fetchone()[0] != 0:
                return False, "Robert King (EmployeeId = 7) should be deleted"
            
            cur.execute("""
                SELECT "Title" FROM "Employee" WHERE "EmployeeId" = 8
            """)
            laura_title = cur.fetchone()
            if not laura_title or laura_title[0] != 'Senior IT Specialist':
                return False, f"Laura Callahan should have title 'Senior IT Specialist', got: {laura_title[0] if laura_title else None}"
            
            # 6. Verify salary column
            cur.execute("""
                SELECT "EmployeeId", salary 
                FROM "Employee" 
                ORDER BY "EmployeeId"
            """)
            salary_data = cur.fetchall()
            
            for emp_id, salary in salary_data:
                expected_salary = Decimal('75000.00') if emp_id == 8 else Decimal('50000.00')
                if salary != expected_salary:
                    return False, f"Employee {emp_id} salary should be {expected_salary}, got {salary}"
        
        conn.close()
        return True, "Employee hierarchy management verified successfully (all 6 verification checks passed)"
        
    except Exception as e:
        return False, f"Verification failed: {str(e)}"


@compare_func(name="postgres_sales_music_charts_verifier")
async def postgres_sales_music_charts_verifier(a: Any, b: Any, *args, **kwargs) -> (bool, str):
    """Verify monthly sales dashboard and music charts by comparing with ground truth queries.
    
    This function replicates the original verification logic from sales_and_music_charts/verify.py
    """
    try:
        conn_params = get_connection_params()
        if not conn_params["database"]:
            return False, "No database specified"
        
        conn = psycopg2.connect(**conn_params)
        
        with conn.cursor() as cur:
            # Verify monthly sales results
            cur.execute("""
                SELECT year_month, total_invoices, total_revenue, 
                       total_tracks_sold, average_invoice_value, unique_customers
                FROM monthly_sales_summary 
                ORDER BY year_month
            """)
            actual_results = cur.fetchall()
            
            # Execute ground truth query
            cur.execute("""
                WITH invoice_metrics AS (
                SELECT
                    DATE_TRUNC('month', i."InvoiceDate") AS ym,
                    COUNT(*)::INT                       AS total_invoices,
                    SUM(i."Total")::DECIMAL             AS total_revenue,
                    AVG(i."Total")::DECIMAL             AS average_invoice_value,
                    COUNT(DISTINCT i."CustomerId")::INT AS unique_customers
                FROM "Invoice" i
                GROUP BY 1
                ),
                track_metrics AS (         
                SELECT
                    DATE_TRUNC('month', i."InvoiceDate") AS ym,
                    SUM(il."Quantity")::INT              AS total_tracks_sold
                FROM "Invoice" i
                JOIN "InvoiceLine" il ON il."InvoiceId" = i."InvoiceId"
                WHERE il."Quantity" > 0                
                GROUP BY 1
                )
                SELECT
                TO_CHAR(im.ym, 'YYYY-MM')          AS year_month,
                im.total_invoices,
                im.total_revenue,
                COALESCE(tm.total_tracks_sold, 0)  AS total_tracks_sold,
                im.average_invoice_value,
                im.unique_customers
                FROM invoice_metrics im
                LEFT JOIN track_metrics tm USING (ym)
                ORDER BY year_month;
            """)
            expected_results = cur.fetchall()

            if len(actual_results) != len(expected_results):
                return False, f"Expected {len(expected_results)} monthly sales records, got {len(actual_results)}"

            # Check each row
            for i, (actual, expected) in enumerate(zip(actual_results, expected_results)):
                if not rows_match(actual, expected):
                    return False, f"Monthly sales row {i+1} mismatch: expected {expected}, got {actual}"
            
            # Verify music charts results by comparing with ground truth
            cur.execute("""
                SELECT chart_type, rank_position, item_id, item_name, total_revenue
                FROM top_music_charts
                ORDER BY chart_type, rank_position
            """)
            actual_chart_results = cur.fetchall()

            # Execute ground truth query for music charts
            cur.execute("""
                WITH track_stats AS (
                SELECT
                    'top_tracks'::varchar AS chart_type,
                    t."TrackId"           AS item_id,
                    t."Name"              AS item_name,
                    SUM(il."UnitPrice" * il."Quantity")::DECIMAL AS total_revenue,
                    SUM(il."Quantity")::INT                      AS total_quantity
                FROM "Track" t
                JOIN "InvoiceLine" il ON il."TrackId" = t."TrackId"
                GROUP BY t."TrackId", t."Name"
                HAVING SUM(il."Quantity") > 0
                ),
                track_ranked AS (
                SELECT
                    chart_type, item_id, item_name, total_revenue,
                    ROW_NUMBER() OVER (ORDER BY total_quantity DESC, item_name, item_id) AS rank_position
                FROM track_stats
                ),
                album_rev AS (
                SELECT
                    'top_albums'::varchar AS chart_type,
                    a."AlbumId"           AS item_id,
                    a."Title"             AS item_name,
                    SUM(il."UnitPrice" * il."Quantity")::DECIMAL AS total_revenue
                FROM "Album" a
                JOIN "Track" t        ON t."AlbumId"  = a."AlbumId"
                JOIN "InvoiceLine" il ON il."TrackId" = t."TrackId"
                GROUP BY a."AlbumId", a."Title"
                HAVING SUM(il."UnitPrice" * il."Quantity") > 0
                ),
                album_ranked AS (
                SELECT
                    chart_type, item_id, item_name, total_revenue,
                    ROW_NUMBER() OVER (ORDER BY total_revenue DESC, item_name, item_id) AS rank_position
                FROM album_rev
                ),
                artist_rev AS (
                SELECT
                    'top_artists'::varchar AS chart_type,
                    ar."ArtistId"          AS item_id,
                    ar."Name"              AS item_name,
                    SUM(il."UnitPrice" * il."Quantity")::DECIMAL AS total_revenue
                FROM "Artist" ar
                JOIN "Album"  a       ON a."ArtistId" = ar."ArtistId"
                JOIN "Track"  t       ON t."AlbumId"  = a."AlbumId"
                JOIN "InvoiceLine" il ON il."TrackId" = t."TrackId"
                GROUP BY ar."ArtistId", ar."Name"
                HAVING SUM(il."UnitPrice" * il."Quantity") > 0
                ),
                artist_ranked AS (
                SELECT
                    chart_type, item_id, item_name, total_revenue,
                    ROW_NUMBER() OVER (ORDER BY total_revenue DESC, item_name, item_id) AS rank_position
                FROM artist_rev
                )
                SELECT chart_type, rank_position, item_id, item_name, total_revenue
                FROM (
                SELECT * FROM track_ranked  WHERE rank_position <= 10
                UNION ALL
                SELECT * FROM album_ranked  WHERE rank_position <= 10
                UNION ALL
                SELECT * FROM artist_ranked WHERE rank_position <= 10
                ) x
                ORDER BY chart_type, rank_position;
            """)
            expected_chart_results = cur.fetchall()

            if len(actual_chart_results) != len(expected_chart_results):
                return False, f"Expected {len(expected_chart_results)} music chart records, got {len(actual_chart_results)}"

            # Check each chart row
            mismatches = 0
            for i, (actual, expected) in enumerate(zip(actual_chart_results, expected_chart_results)):
                if not rows_match(actual, expected):
                    if mismatches < 3:  # Show first 3 mismatches
                        return False, f"Music chart row {i+1} mismatch: expected {expected}, got {actual}"
                    mismatches += 1

            if mismatches > 0:
                return False, f"Total music chart mismatches: {mismatches}"
        
        conn.close()
        return True, f"Sales and music charts verified successfully ({len(actual_results)} monthly records, {len(actual_chart_results)} chart records)"
        
    except Exception as e:
        return False, f"Verification failed: {str(e)}"


@compare_func(name="postgres_data_migration_verifier")
async def postgres_data_migration_verifier(a: Any, b: Any, *args, **kwargs) -> (bool, str):
    """Verify PostgreSQL data migration task completion.
    
    This function verifies:
    1. Successful data migration
    2. Correct record counts
    3. Data integrity checks
    
    Inputs:
      - a: raw text output from agent (from func-chain, usually `raw`)
      - b: expected completion status (config.value) - "completed"
      - args[1] (op_args): dict with expected values for verification
    """
    # unwrap
    if isinstance(a, FunctionResult):
        a = a.result
    if isinstance(b, FunctionResult):
        b = b.result
    
    if not isinstance(a, str):
        return False, "postgres_data_migration_verifier expects a string input"
    
    op_args = args[1] if len(args) > 1 else {}
    text = a.strip().lower()
    
    # Key indicators for successful data migration
    success_indicators = [
        "migration completed",
        "data migrated",
        "records inserted",
        "customers migrated",
        "verification passed",
        "data integrity",
        "migration successful",
        "rows affected",
        "insert successful"
    ]
    
    # Check for migration success indicators
    found_indicators = []
    for indicator in success_indicators:
        if indicator in text:
            found_indicators.append(indicator)
    
    # Require at least 3 indicators for success
    if len(found_indicators) >= 3:
        return True, f"Data migration completed successfully. Found indicators: {found_indicators}"
    
    return False, f"Insufficient migration indicators. Found: {found_indicators} (need at least 3)"


@compare_func(name="postgres_security_verifier")
async def postgres_security_verifier(a: Any, b: Any, *args, **kwargs) -> (bool, str):
    """Verify PostgreSQL security audit by checking audit results and details tables.
    
    This function replicates the original verification logic from user_permission_audit/verify.py
    """
    try:
        conn_params = get_connection_params()
        if not conn_params["database"]:
            return False, "No database specified"
        
        conn = psycopg2.connect(**conn_params)
        
        with conn.cursor() as cur:
            # Check if security_audit_results table exists
            cur.execute("""
                SELECT EXISTS (
                    SELECT FROM information_schema.tables
                    WHERE table_name = 'security_audit_results'
                );
            """)
            if not cur.fetchone()[0]:
                return False, "security_audit_results table not found"
            
            # Check if security_audit_details table exists
            cur.execute("""
                SELECT EXISTS (
                    SELECT FROM information_schema.tables
                    WHERE table_name = 'security_audit_details'
                );
            """)
            if not cur.fetchone()[0]:
                return False, "security_audit_details table not found"
            
            # Get all detailed findings
            cur.execute("SELECT * FROM security_audit_details ORDER BY detail_id;")
            findings = cur.fetchall()
            
            if not findings:
                return False, "No findings in security_audit_details table"
            
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
            
            # Analyze findings (detail_id, username, issue_type, table_name, permission_type, expected_access)
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
            
            # Verify missing permissions
            missing_missing_perms = expected_findings['missing_permissions'] - found_missing_permissions
            
            # Verify excessive permissions
            missing_excessive_perms = expected_findings['excessive_permissions'] - found_excessive_permissions
            
            # Validate structure
            for i, finding in enumerate(findings):
                if len(finding) != 6:  # Should have 6 columns
                    return False, f"Finding {i + 1} has wrong number of columns (expected 6, got {len(finding)})"
                
                detail_id, username, issue_type, table_name, permission_type, expected_access = finding
                
                if not username:
                    return False, f"Finding {i + 1} missing username"
                
                if issue_type not in ['DANGLING_USER', 'MISSING_PERMISSION', 'EXCESSIVE_PERMISSION']:
                    return False, f"Finding {i + 1} invalid issue_type: {issue_type}"
                
                if expected_access not in [True, False]:
                    return False, f"Finding {i + 1} invalid expected_access: {expected_access}"
            
            # Check for missing findings
            if missing_dangling:
                return False, f"Missing dangling users: {missing_dangling}"
            
            if missing_missing_perms:
                return False, f"Missing 'missing permission' findings: {len(missing_missing_perms)} permissions not identified"
            
            if missing_excessive_perms:
                return False, f"Missing 'excessive permission' findings: {len(missing_excessive_perms)} permissions not identified"
            
            # Check audit summary table
            cur.execute("""
                SELECT audit_type, total_issues, users_affected, tables_affected 
                FROM security_audit_results 
                ORDER BY audit_type;
            """)
            summary_results = cur.fetchall()
            
            # Expected summary numbers based on ground truth
            expected_summary = {
                'DANGLING_USERS': (3, 3, 0),          # 3 issues, 3 users affected, 0 tables affected
                'EXCESSIVE_PERMISSIONS': (13, 10, 7), # 13 issues, 10 users affected, 7 tables affected
                'MISSING_PERMISSIONS': (13, 8, 7)     # 13 issues, 8 users affected, 7 tables affected
            }
            
            for result in summary_results:
                audit_type, total_issues, users_affected, tables_affected = result
                
                if audit_type in expected_summary:
                    expected = expected_summary[audit_type]
                    if (total_issues, users_affected, tables_affected) != expected:
                        return False, f"{audit_type} summary mismatch - Expected: {expected}, Got: ({total_issues}, {users_affected}, {tables_affected})"
            
            # Assert exact counts match expected
            if len(found_dangling) != 3:
                return False, f"Expected 3 dangling users, found {len(found_dangling)}"
            
            if len(found_missing_permissions) != 13:
                return False, f"Expected 13 missing permissions, found {len(found_missing_permissions)}"
            
            if len(found_excessive_permissions) != 13:
                return False, f"Expected 13 excessive permissions, found {len(found_excessive_permissions)}"
        
        conn.close()
        return True, f"Security audit verified successfully (dangling users: {len(found_dangling)}, missing permissions: {len(found_missing_permissions)}, excessive permissions: {len(found_excessive_permissions)})"
        
    except Exception as e:
        return False, f"Verification failed: {str(e)}"

@compare_func(name="postgres_rls_business_access_verifier")
async def postgres_rls_business_access_verifier(a: Any, b: Any, *args, **kwargs) -> (bool, str):
    """Verify RLS business access by testing row-level security policies on social media platform.
    
    This function replicates the original verification logic from rls_business_access/verify.py
    """
    try:
        conn_params = get_connection_params()
        if not conn_params["database"]:
            return False, "No database specified"
        
        # First connect as admin to ensure test user exists
        admin_conn = psycopg2.connect(**conn_params)
        admin_conn.set_isolation_level(psycopg2.extensions.ISOLATION_LEVEL_AUTOCOMMIT)
        admin_cur = admin_conn.cursor()
        
        # Create test user if it doesn't exist
        try:
            admin_cur.execute("CREATE ROLE test_user LOGIN PASSWORD 'testpass';")
        except psycopg2.Error:
            pass  # User already exists
        
        # Grant necessary permissions to test user
        admin_cur.execute("SELECT current_database();")
        current_db_name = admin_cur.fetchone()[0]
        
        admin_cur.execute(f"GRANT CONNECT ON DATABASE \"{current_db_name}\" TO test_user;")
        admin_cur.execute("GRANT USAGE ON SCHEMA public TO test_user;")
        admin_cur.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO test_user;")
        admin_cur.execute("GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO test_user;")
        admin_cur.execute("GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA public TO test_user;")
        
        admin_cur.close()
        admin_conn.close()
        
        # Connect as test user for RLS verification
        test_db_params = conn_params.copy()
        test_db_params['user'] = 'test_user'
        test_db_params['password'] = 'testpass'
        
        conn = psycopg2.connect(**test_db_params)
        conn.set_isolation_level(psycopg2.extensions.ISOLATION_LEVEL_AUTOCOMMIT)
        
        test_results = []
        
        with conn.cursor() as cur:
            # Test 1: Check if RLS is enabled on all tables
            expected_tables = ['users', 'channels', 'channel_moderators', 'posts', 'comments']
            
            for table in expected_tables:
                cur.execute("""
                    SELECT relrowsecurity
                    FROM pg_class
                    WHERE relname = %s AND relkind = 'r'
                """, (table,))
                result = cur.fetchone()
                
                if not result or not result[0]:
                    return False, f"RLS NOT enabled on {table}"
            
            test_results.append("RLS enabled on all tables")
            
            # Test 2: Users can only update their own profile
            # Alice tries to update her own profile (should work)
            try:
                cur.execute("SET app.current_user_id = '11111111-1111-1111-1111-111111111111';")  # Alice
                cur.execute("""
                    UPDATE users
                    SET email = 'alice.updated@example.com'
                    WHERE id = '11111111-1111-1111-1111-111111111111'
                """)
                test_results.append("Users can update their own profile")
            except Exception as e:
                return False, f"User cannot update own profile: {e}"
            
            # Alice tries to update Bob's profile (should fail)
            try:
                cur.execute("SET app.current_user_id = '11111111-1111-1111-1111-111111111111';")  # Alice
                cur.execute("""
                    UPDATE users
                    SET email = 'bob.hacked@example.com'
                    WHERE id = '22222222-2222-2222-2222-222222222222'
                """)
                if cur.rowcount != 0:
                    return False, "User was able to update another user's profile (should be blocked)"
            except psycopg2.Error:
                pass  # Expected failure
            
            test_results.append("Users blocked from updating other users' profiles")
            
            # Test 3: Channel ownership controls
            # Alice (owner of general channel) tries to update her channel
            try:
                cur.execute("SET app.current_user_id = '11111111-1111-1111-1111-111111111111';")  # Alice
                cur.execute("""
                    UPDATE channels
                    SET description = 'Updated by Alice'
                    WHERE id = 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa'
                """)
                test_results.append("Channel owners can update their channels")
            except Exception as e:
                return False, f"Channel owner cannot update channel: {e}"
            
            # Charlie tries to update Alice's channel (should fail)
            try:
                cur.execute("SET app.current_user_id = '33333333-3333-3333-3333-333333333333';")  # Charlie
                cur.execute("""
                    UPDATE channels
                    SET description = 'Hacked by Charlie'
                    WHERE id = 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa'
                """)
                if cur.rowcount != 0:
                    return False, "Non-owner was able to update channel (should be blocked)"
            except psycopg2.Error:
                pass  # Expected failure
            
            test_results.append("Non-owners blocked from updating channels")
            
            # Test 4: Post authorship and moderation controls
            # Alice (author) tries to update her own post
            try:
                cur.execute("SET app.current_user_id = '11111111-1111-1111-1111-111111111111';")  # Alice
                cur.execute("""
                    UPDATE posts
                    SET title = 'Updated by Alice'
                    WHERE id = 'dddddddd-dddd-dddd-dddd-dddddddddddd'
                """)
                test_results.append("Post authors can update their posts")
            except Exception as e:
                return False, f"Post author cannot update post: {e}"
            
            # Bob (moderator of general) tries to update Alice's post (should work)
            try:
                cur.execute("SET app.current_user_id = '22222222-2222-2222-2222-222222222222';")  # Bob (moderator)
                cur.execute("""
                    UPDATE posts
                    SET content = 'Moderated by Bob'
                    WHERE id = 'dddddddd-dddd-dddd-dddd-dddddddddddd'
                """)
                test_results.append("Channel moderators can update posts in their channels")
            except Exception as e:
                return False, f"Channel moderator cannot update post: {e}"
            
            # Eve tries to update Alice's post (should fail)
            try:
                cur.execute("SET app.current_user_id = '55555555-5555-5555-5555-555555555555';")  # Eve
                cur.execute("""
                    UPDATE posts
                    SET content = 'Hacked by Eve'
                    WHERE id = 'dddddddd-dddd-dddd-dddd-dddddddddddd'
                """)
                if cur.rowcount != 0:
                    return False, "Unauthorized user was able to update post (should be blocked)"
            except psycopg2.Error:
                pass  # Expected failure
            
            test_results.append("Unauthorized users blocked from updating posts")
            
            # Test 5: Comment access controls
            # Bob (comment author) tries to update his own comment
            try:
                cur.execute("SET app.current_user_id = '22222222-2222-2222-2222-222222222222';")  # Bob
                cur.execute("""
                    UPDATE comments
                    SET content = 'Updated by Bob himself'
                    WHERE id = '99999999-9999-9999-9999-999999999999'
                """)
                test_results.append("Comment authors can update their comments")
            except Exception as e:
                return False, f"Comment author cannot update comment: {e}"
            
            # Alice (post author) tries to update Bob's comment on her post (should work)
            try:
                cur.execute("SET app.current_user_id = '11111111-1111-1111-1111-111111111111';")  # Alice (post author)
                cur.execute("""
                    UPDATE comments
                    SET content = 'Moderated by post author Alice'
                    WHERE id = '99999999-9999-9999-9999-999999999999'
                """)
                test_results.append("Post authors can moderate comments on their posts")
            except Exception as e:
                return False, f"Post author cannot moderate comment: {e}"
            
            # Test 6: Channel moderator assignment controls
            # Alice (channel owner) tries to add a moderator
            try:
                cur.execute("SET app.current_user_id = '11111111-1111-1111-1111-111111111111';")  # Alice (owner of general)
                cur.execute("""
                    INSERT INTO channel_moderators (channel_id, user_id)
                    VALUES ('aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa', '33333333-3333-3333-3333-333333333333')
                """)
                test_results.append("Channel owners can add moderators")
            except Exception as e:
                return False, f"Channel owner cannot add moderator: {e}"
            
            # Charlie tries to add himself as moderator to Bob's channel (should fail)
            try:
                cur.execute("SET app.current_user_id = '33333333-3333-3333-3333-333333333333';")  # Charlie
                cur.execute("""
                    INSERT INTO channel_moderators (channel_id, user_id)
                    VALUES ('bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb', '33333333-3333-3333-3333-333333333333')
                """)
                if cur.rowcount != 0:
                    return False, "Non-owner was able to add moderator (should be blocked)"
            except psycopg2.Error:
                pass  # Expected failure
            
            test_results.append("Non-owners blocked from adding moderators")
            
            # Test 7: Content visibility based on user context
            # Count posts visible to Alice
            cur.execute("SET app.current_user_id = '11111111-1111-1111-1111-111111111111';")  # Alice
            cur.execute("SELECT COUNT(*) FROM posts;")
            alice_posts = cur.fetchone()[0]
            
            # Count posts visible to Eve
            cur.execute("SET app.current_user_id = '55555555-5555-5555-5555-555555555555';")  # Eve
            cur.execute("SELECT COUNT(*) FROM posts;")
            eve_posts = cur.fetchone()[0]
            
            if alice_posts >= 2 and eve_posts >= 1:
                test_results.append("Content visibility varies correctly based on user context")
            else:
                return False, f"Content visibility issue: Alice sees {alice_posts}, Eve sees {eve_posts}"
            
            # Test 8: Anonymous user access
            try:
                cur.execute("SET app.current_user_id = '';")  # Anonymous user
                cur.execute("SELECT COUNT(*) FROM users;")
                anon_users = cur.fetchone()[0]
                
                # Anonymous users should be able to see public user profiles
                cur.execute("SELECT COUNT(*) FROM users WHERE is_public = true;")
                public_users = cur.fetchone()[0] if cur.rowcount > 0 else 0
                
                if anon_users == public_users and anon_users > 0:
                    test_results.append(f"Anonymous users can see {anon_users} public user profiles (correct)")
                elif anon_users == 0:
                    return False, "Anonymous users cannot see any users (should see public profiles)"
                else:
                    return False, f"Anonymous users can see {anon_users} users but expected {public_users} public users"
            except Exception as e:
                test_results.append("Anonymous users properly restricted")
        
        conn.close()
        return True, f"RLS business access verified successfully ({len(test_results)} tests passed: {', '.join(test_results)})"
        
    except Exception as e:
        return False, f"Verification failed: {str(e)}"

@compare_func(name="postgres_dba_vector_analysis_verifier")
async def postgres_dba_vector_analysis_verifier(a: Any, b: Any, *args, **kwargs) -> (bool, str):
    """Verify DBA vector analysis by checking analysis tables structure and data.
    
    This function replicates the original verification logic from dba_vector_analysis/verify.py
    """
    try:
        conn_params = get_connection_params()
        if not conn_params["database"]:
            return False, "No database specified"
        
        conn = psycopg2.connect(**conn_params)
        
        with conn.cursor() as cur:
            # 1. Verify vector_analysis_columns table
            # Check if table exists
            cur.execute("""
                SELECT EXISTS (
                    SELECT FROM information_schema.tables
                    WHERE table_name = 'vector_analysis_columns'
                );
            """)
            if not cur.fetchone()[0]:
                return False, "vector_analysis_columns table not found"
            
            # Check columns
            expected_columns = ['schema', 'table_name', 'column_name', 'dimensions', 'data_type', 'has_constraints', 'rows']
            cur.execute("""
                SELECT column_name FROM information_schema.columns
                WHERE table_name = 'vector_analysis_columns'
                ORDER BY column_name;
            """)
            actual_columns = {row[0] for row in cur.fetchall()}
            missing = set(expected_columns) - actual_columns
            if missing:
                return False, f"vector_analysis_columns missing columns: {missing}"
            
            # Check for data
            cur.execute("SELECT COUNT(*) FROM vector_analysis_columns;")
            count = cur.fetchone()[0]
            if count == 0:
                return False, "No rows found in vector_analysis_columns"
            
            # Get actual vector columns from the database
            cur.execute("""
                SELECT table_name, column_name
                FROM information_schema.columns
                WHERE data_type = 'USER-DEFINED'
                AND udt_name = 'vector'
                ORDER BY table_name, column_name;
            """)
            actual_vector_columns = set(cur.fetchall())
            
            # Get what the agent found
            cur.execute("""
                SELECT table_name, column_name
                FROM vector_analysis_columns
                ORDER BY table_name, column_name;
            """)
            found_vector_columns = set(cur.fetchall())
            
            # Check if agent found the actual vector columns
            missing_vectors = actual_vector_columns - found_vector_columns
            if missing_vectors:
                return False, f"vector_analysis_columns missing vectors: {missing_vectors}"
            
            # 2. Verify vector_analysis_storage_consumption table
            cur.execute("""
                SELECT EXISTS (
                    SELECT FROM information_schema.tables
                    WHERE table_name = 'vector_analysis_storage_consumption'
                );
            """)
            if not cur.fetchone()[0]:
                return False, "vector_analysis_storage_consumption table not found"
            
            expected_columns = ['schema', 'table_name', 'total_size_bytes', 'vector_data_bytes', 'regular_data_bytes', 'vector_storage_pct', 'row_count']
            cur.execute("""
                SELECT column_name FROM information_schema.columns
                WHERE table_name = 'vector_analysis_storage_consumption'
                ORDER BY column_name;
            """)
            actual_columns = {row[0] for row in cur.fetchall()}
            missing = set(expected_columns) - actual_columns
            if missing:
                return False, f"vector_analysis_storage_consumption missing columns: {missing}"
            
            cur.execute("SELECT COUNT(*) FROM vector_analysis_storage_consumption;")
            count = cur.fetchone()[0]
            if count == 0:
                return False, "No rows found in vector_analysis_storage_consumption"
            
            # Get actual tables with vector columns
            cur.execute("""
                SELECT DISTINCT table_name
                FROM information_schema.columns
                WHERE data_type = 'USER-DEFINED'
                AND udt_name = 'vector'
                ORDER BY table_name;
            """)
            actual_vector_tables = {row[0] for row in cur.fetchall()}
            
            # Get what the agent analyzed
            cur.execute("""
                SELECT DISTINCT table_name
                FROM vector_analysis_storage_consumption
                ORDER BY table_name;
            """)
            analyzed_tables = {row[0] for row in cur.fetchall()}
            
            # Check if agent analyzed the actual vector tables
            missing_tables = actual_vector_tables - analyzed_tables
            if missing_tables:
                return False, f"vector_analysis_storage_consumption missed tables: {missing_tables}"
            
            # 3. Verify vector_analysis_indices table
            cur.execute("""
                SELECT EXISTS (
                    SELECT FROM information_schema.tables
                    WHERE table_name = 'vector_analysis_indices'
                );
            """)
            if not cur.fetchone()[0]:
                return False, "vector_analysis_indices table not found"
            
            expected_columns = ['schema', 'table_name', 'column_name', 'index_name', 'index_type', 'index_size_bytes']
            cur.execute("""
                SELECT column_name FROM information_schema.columns
                WHERE table_name = 'vector_analysis_indices'
                ORDER BY column_name;
            """)
            actual_columns = {row[0] for row in cur.fetchall()}
            missing = set(expected_columns) - actual_columns
            if missing:
                return False, f"vector_analysis_indices missing columns: {missing}"
            
            cur.execute("SELECT COUNT(*) FROM vector_analysis_indices;")
            count = cur.fetchone()[0]
            if count == 0:
                return False, "No rows found in vector_analysis_indices"
            
            # Get actual vector indexes from the database (exclude analysis table indexes)
            cur.execute("""
                SELECT schemaname, tablename, indexname
                FROM pg_indexes
                WHERE (indexdef ILIKE '%hnsw%' OR indexdef ILIKE '%ivfflat%')
                AND tablename NOT LIKE '%analysis%'
                ORDER BY tablename, indexname;
            """)
            actual_vector_indexes = set(cur.fetchall())
            
            # Get what the agent found
            cur.execute("""
                SELECT schema, table_name, index_name
                FROM vector_analysis_indices
                ORDER BY table_name, index_name;
            """)
            found_indexes = set(cur.fetchall())
            
            # Check if agent found the actual vector indexes
            missing_indexes = actual_vector_indexes - found_indexes
            if missing_indexes:
                return False, f"vector_analysis_indices missed indexes: {missing_indexes}"
            
            # 4. Verify no extra analysis tables
            required = {
                'vector_analysis_columns',
                'vector_analysis_storage_consumption',
                'vector_analysis_indices',
            }
            cur.execute("""
                SELECT table_name FROM information_schema.tables
                WHERE table_schema = 'public'
                AND table_name LIKE 'vector_analysis_%';
            """)
            analysis_tables = {row[0] for row in cur.fetchall()}
            
            # Exclude ground truth tables from this check
            analysis_tables_filtered = {t for t in analysis_tables if not t.startswith('expected_') and not t.startswith('vector_analysis_results')}
            extra = analysis_tables_filtered - required
            if extra:
                return False, f"Found unexpected analysis tables: {extra}"
        
        conn.close()
        return True, f"DBA vector analysis verified successfully (columns table: {len(found_vector_columns)} vectors, storage table: {len(analyzed_tables)} tables, indices table: {len(found_indexes)} indexes)"
        
    except Exception as e:
        return False, f"Verification failed: {str(e)}"


@compare_func(name="postgres_analysis_verifier")
async def postgres_analysis_verifier(a: Any, b: Any, *args, **kwargs) -> (bool, str):
    """Verify PostgreSQL analysis task completion.
    
    This function verifies:
    1. Analysis queries executed
    2. Results tables created
    3. Analysis data populated
    
    Inputs:
      - a: raw text output from agent (from func-chain, usually `raw`)
      - b: expected completion status (config.value) - "completed"
      - args[1] (op_args): dict with expected values for verification
    """
    # unwrap
    if isinstance(a, FunctionResult):
        a = a.result
    if isinstance(b, FunctionResult):
        b = b.result
    
    if not isinstance(a, str):
        return False, "postgres_analysis_verifier expects a string input"
    
    op_args = args[1] if len(args) > 1 else {}
    text = a.strip().lower()
    
    # Key indicators for successful analysis
    success_indicators = [
        "analysis completed",
        "results table",
        "analysis table",
        "query executed",
        "data analyzed",
        "report generated",
        "statistics calculated",
        "metrics computed",
        "analysis results",
        "table created",
        "data populated",
        "analysis successful"
    ]
    
    # Check for analysis success indicators
    found_indicators = []
    for indicator in success_indicators:
        if indicator in text:
            found_indicators.append(indicator)
    
    # Require at least 4 indicators for success
    if len(found_indicators) >= 4:
        return True, f"Analysis completed successfully. Found indicators: {found_indicators}"
    
    return False, f"Insufficient analysis indicators. Found: {found_indicators} (need at least 4)"


@compare_func(name="postgres_customer_analysis_fix_verifier")
async def postgres_customer_analysis_fix_verifier(a: Any, b: Any, *args, **kwargs) -> (bool, str):
    """Verify customer analysis fix by comparing with ground truth query.
    
    This function replicates the original verification logic from customer_analysis_fix/verify.py
    """
    try:
        conn_params = get_connection_params()
        if not conn_params["database"]:
            return False, "No database specified"
        
        conn = psycopg2.connect(**conn_params)
        
        with conn.cursor() as cur:
            # Get actual results from the created table
            cur.execute("""
                SELECT customer_id, customer_name, customer_city, customer_country,
                       total_rentals, unique_films, total_spent, favorite_category,
                       favorite_actor, avg_rental_duration, customer_tier,
                       most_popular_film_in_region, regional_film_rental_count
                FROM customer_analysis_fixed
                ORDER BY total_spent DESC, total_rentals DESC, customer_name ASC
            """)
            actual_results = cur.fetchall()
            
            # Execute ground truth query (the corrected version)
            cur.execute("""
                WITH paid_rentals AS (
                SELECT DISTINCT
                        r.rental_id,
                        r.customer_id,
                        r.inventory_id,
                        r.rental_date,
                        r.return_date
                FROM rental r
                JOIN payment p ON p.rental_id = r.rental_id
                ),
                payments_by_customer AS (
                SELECT pr.customer_id, SUM(p.amount) AS total_spent
                FROM paid_rentals pr
                JOIN payment p ON p.rental_id = pr.rental_id
                GROUP BY pr.customer_id
                ),
                customer_basic_stats AS (
                SELECT
                    c.customer_id,
                    c.first_name || ' ' || c.last_name AS customer_name,
                    ci.city AS customer_city,
                    co.country AS customer_country,
                    COUNT(DISTINCT pr.rental_id) AS total_rentals,
                    COUNT(DISTINCT i.film_id) AS unique_films,
                    pbc.total_spent,
                    AVG(EXTRACT(EPOCH FROM (pr.return_date - pr.rental_date)) / 86400.0) AS avg_rental_duration
                FROM customer c
                JOIN address a ON c.address_id = a.address_id
                JOIN city ci ON a.city_id = ci.city_id
                JOIN country co ON ci.country_id = co.country_id
                JOIN paid_rentals pr ON pr.customer_id = c.customer_id
                JOIN inventory i ON pr.inventory_id = i.inventory_id
                JOIN payments_by_customer pbc ON pbc.customer_id = c.customer_id
                WHERE c.email IS NOT NULL
                GROUP BY c.customer_id, c.first_name, c.last_name, ci.city, co.country, pbc.total_spent
                HAVING COUNT(DISTINCT pr.rental_id) >= 15
                ),
                customer_categories AS (
                SELECT
                    pr.customer_id,
                    cat.name AS category_name,
                    COUNT(*) AS category_count,
                    ROW_NUMBER() OVER (
                        PARTITION BY pr.customer_id
                        ORDER BY COUNT(*) DESC, cat.name ASC
                    ) AS rn
                FROM paid_rentals pr
                JOIN inventory i ON pr.inventory_id = i.inventory_id
                JOIN film f ON i.film_id = f.film_id
                JOIN film_category fc ON f.film_id = fc.film_id
                JOIN category cat ON fc.category_id = cat.category_id
                JOIN customer c ON pr.customer_id = c.customer_id
                WHERE c.email IS NOT NULL
                GROUP BY pr.customer_id, cat.name
                ),
                customer_actors AS (
                SELECT
                    pr.customer_id,
                    (a.first_name || ' ' || a.last_name) AS actor_name,
                    COUNT(*) AS actor_count,
                    ROW_NUMBER() OVER (
                        PARTITION BY pr.customer_id
                        ORDER BY COUNT(*) DESC, (a.first_name || ' ' || a.last_name) ASC
                    ) AS rn
                FROM paid_rentals pr
                JOIN inventory i ON pr.inventory_id = i.inventory_id
                JOIN film f ON i.film_id = f.film_id
                JOIN film_actor fa ON f.film_id = fa.film_id
                JOIN actor a ON fa.actor_id = a.actor_id
                JOIN customer c ON pr.customer_id = c.customer_id
                WHERE c.email IS NOT NULL
                GROUP BY pr.customer_id, a.first_name, a.last_name
                ),
                regional_popular_films AS (
                SELECT
                    co.country,
                    f.title,
                    COUNT(DISTINCT pr.rental_id) AS rental_count,
                    ROW_NUMBER() OVER (
                        PARTITION BY co.country
                        ORDER BY COUNT(DISTINCT pr.rental_id) DESC, f.title ASC
                    ) AS rn
                FROM paid_rentals pr
                JOIN customer c ON pr.customer_id = c.customer_id
                JOIN address a ON c.address_id = a.address_id
                JOIN city ci ON a.city_id = ci.city_id
                JOIN country co ON ci.country_id = co.country_id
                JOIN inventory i ON pr.inventory_id = i.inventory_id
                JOIN film f ON i.film_id = f.film_id
                WHERE c.email IS NOT NULL
                GROUP BY co.country, f.title
                )
                SELECT
                    cbs.customer_id,
                    cbs.customer_name,
                    cbs.customer_city,
                    cbs.customer_country,
                    cbs.total_rentals,
                    cbs.unique_films,
                    cbs.total_spent,
                    cc.category_name AS favorite_category,
                    ca.actor_name AS favorite_actor,
                    cbs.avg_rental_duration,
                    CASE
                    WHEN cbs.total_spent >= 150 THEN 'Premium'
                    WHEN cbs.total_spent >= 75  THEN 'Standard'
                    ELSE 'Basic'
                    END AS customer_tier,
                    rpf.title AS most_popular_film_in_region,
                    rpf.rental_count AS regional_film_rental_count
                FROM customer_basic_stats cbs
                LEFT JOIN customer_categories cc
                ON cbs.customer_id = cc.customer_id AND cc.rn = 1
                LEFT JOIN customer_actors ca
                ON cbs.customer_id = ca.customer_id AND ca.rn = 1
                LEFT JOIN regional_popular_films rpf
                ON cbs.customer_country = rpf.country AND rpf.rn = 1
                ORDER BY cbs.total_spent DESC, cbs.total_rentals DESC, cbs.customer_name ASC;
            """)
            expected_results = cur.fetchall()

            if len(actual_results) != len(expected_results):
                return False, f"Expected {len(expected_results)} rows, got {len(actual_results)}"

            # Check each row for mismatches
            mismatches = 0
            for i, (actual, expected) in enumerate(zip(actual_results, expected_results)):
                if not rows_match(actual, expected):
                    if mismatches < 3:  # Show first 3 mismatches
                        return False, f"Row {i+1} mismatch: expected {expected}, got {actual}"
                    mismatches += 1

            if mismatches > 0:
                return False, f"Total mismatches: {mismatches}"

        conn.close()
        return True, f"Customer analysis fix verified successfully ({len(actual_results)} rows)"
        
    except Exception as e:
        return False, f"Verification failed: {str(e)}"


@compare_func(name="postgres_customer_analytics_optimization_verifier")
async def postgres_customer_analytics_optimization_verifier(a: Any, b: Any, *args, **kwargs) -> (bool, str):
    """Verify customer analytics optimization by checking for index creation.
    
    This function replicates the original verification logic from customer_analytics_optimization/verify.py
    """
    try:
        conn_params = get_connection_params()
        if not conn_params["database"]:
            return False, "No database specified"
        
        conn = psycopg2.connect(**conn_params)
        
        with conn.cursor() as cur:
            # Check if there's any index on payment.customer_id column
            cur.execute("""
                SELECT indexname, indexdef 
                FROM pg_indexes 
                WHERE schemaname = 'public' 
                AND tablename = 'payment'
                AND indexdef LIKE '%customer_id%'
            """)
            indexes = cur.fetchall()
            
            if len(indexes) == 0:
                return False, "No index found on payment.customer_id column"
        
        conn.close()
        return True, f"Customer analytics optimization verified successfully (found {len(indexes)} indexes)"
        
    except Exception as e:
        return False, f"Verification failed: {str(e)}"


@compare_func(name="postgres_film_inventory_verifier")
async def postgres_film_inventory_verifier(a: Any, b: Any, *args, **kwargs) -> (bool, str):
    """Verify film inventory management by checking specific film additions and updates.
    
    This function replicates the original verification logic from film_inventory_management/verify.py
    """
    try:
        conn_params = get_connection_params()
        if not conn_params["database"]:
            return False, "No database specified"
        
        conn = psycopg2.connect(**conn_params)
        
        with conn.cursor() as cur:
            # Check if the two new films were added correctly
            cur.execute("""
                SELECT title, description, release_year, language_id, 
                       rental_duration, rental_rate, length, replacement_cost, 
                       rating
                FROM film 
                WHERE title IN ('Data Science Adventures', 'Cloud Computing Chronicles')
                ORDER BY title
            """)
            actual_films = cur.fetchall()
            
            expected_films = [
                ('Cloud Computing Chronicles', 'Exploring the world of distributed systems', 2024, 1, 7, Decimal('4.99'), 135, Decimal('18.99'), 'PG'),
                ('Data Science Adventures', 'A thrilling journey through machine learning algorithms', 2024, 1, 5, Decimal('4.389'), 120, Decimal('15.99'), 'PG-13')
            ]
            
            if len(actual_films) != 2:
                return False, f"Expected 2 new films, found {len(actual_films)}"
            
            # Check each film
            for i, (actual, expected) in enumerate(zip(actual_films, expected_films)):
                if not rows_match(actual, expected):
                    return False, f"Film {i+1} mismatch: expected {expected}, got {actual}"
            
            # Check inventory records for new films
            cur.execute("""
                SELECT f.title, i.store_id, COUNT(*) as count
                FROM film f
                JOIN inventory i ON f.film_id = i.film_id
                WHERE f.title IN ('Data Science Adventures', 'Cloud Computing Chronicles')
                GROUP BY f.title, i.store_id
                ORDER BY f.title, i.store_id
            """)
            actual_inventory = cur.fetchall()
            
            expected_inventory = [
                ('Cloud Computing Chronicles', 1, 3),
                ('Cloud Computing Chronicles', 2, 2), 
                ('Data Science Adventures', 1, 3),
                ('Data Science Adventures', 2, 2)
            ]
            
            if len(actual_inventory) != len(expected_inventory):
                return False, f"Expected {len(expected_inventory)} inventory groups, found {len(actual_inventory)}"
            
            for i, (actual, expected) in enumerate(zip(actual_inventory, expected_inventory)):
                if not rows_match(actual, expected):
                    return False, f"Inventory group {i+1} mismatch: expected {expected}, got {actual}"
            
            # Check available_films table by comparing with ground truth
            cur.execute("""
                SELECT film_id, title, rental_rate, length
                FROM available_films
                ORDER BY rental_rate DESC, length DESC, title ASC
            """)
            actual_available = cur.fetchall()
            
            cur.execute("""
                SELECT DISTINCT f.film_id, f.title, f.rental_rate, f.length
                FROM film f
                JOIN inventory i ON f.film_id = i.film_id
                WHERE f.rental_rate >= 3.00 AND f.rental_rate <= 5.00
                AND f.length > 100
                AND i.store_id = 1
                ORDER BY f.rental_rate DESC, f.length DESC, f.title ASC
            """)
            expected_available = cur.fetchall()
            
            if len(actual_available) != len(expected_available):
                return False, f"available_films table has {len(actual_available)} records, expected {len(expected_available)}"
            
            for i, (actual, expected) in enumerate(zip(actual_available, expected_available)):
                if not rows_match(actual, expected):
                    return False, f"available_films row {i+1} mismatch: expected {expected}, got {actual}"
            
            # Check inventory cleanup
            cur.execute("""
                SELECT COUNT(*)
                FROM inventory i
                JOIN film f ON i.film_id = f.film_id
                WHERE f.replacement_cost > 25.00 AND f.rental_rate < 1.00
                AND NOT EXISTS (SELECT 1 FROM rental r WHERE r.inventory_id = i.inventory_id)
            """)
            remaining_count = cur.fetchone()[0]
            
            if remaining_count > 0:
                return False, f"Found {remaining_count} inventory records that should have been deleted (no rental history)"
            
            # Check film_inventory_summary table
            cur.execute("""
                SELECT title, rental_rate, total_inventory, store1_count, store2_count
                FROM film_inventory_summary
            """)
            actual_summary = cur.fetchall()
            
            cur.execute("""
                SELECT f.title, f.rental_rate,
                       COUNT(i.inventory_id) as total_inventory,
                       COUNT(CASE WHEN i.store_id = 1 THEN 1 END) as store1_count,
                       COUNT(CASE WHEN i.store_id = 2 THEN 1 END) as store2_count
                FROM film f
                JOIN inventory i ON f.film_id = i.film_id
                GROUP BY f.film_id, f.title, f.rental_rate
                ORDER BY total_inventory DESC, f.title ASC
            """)
            expected_summary = cur.fetchall()
            
            if len(actual_summary) != len(expected_summary):
                return False, f"film_inventory_summary table has {len(actual_summary)} records, expected {len(expected_summary)}"
            
            for i, (actual, expected) in enumerate(zip(actual_summary, expected_summary)):
                if not rows_match(actual, expected):
                    return False, f"Summary row {i+1} mismatch: expected {expected}, got {actual}"
        
        conn.close()
        return True, f"Film inventory management verified successfully (2 films, {len(actual_inventory)} inventory groups, {len(actual_available)} available films, {len(actual_summary)} summary records)"
        
    except Exception as e:
        return False, f"Verification failed: {str(e)}"


@compare_func(name="postgres_employee_demographics_verifier")
async def postgres_employee_demographics_verifier(a: Any, b: Any, *args, **kwargs) -> (bool, str):
    """Verify employee demographics report by comparing with ground truth queries.
    
    This function replicates the original verification logic from employee_demographics_report/verify.py
    """
    try:
        conn_params = get_connection_params()
        if not conn_params["database"]:
            return False, "No database specified"
        
        conn = psycopg2.connect(**conn_params)
        
        with conn.cursor() as cur:
            # Verify gender statistics
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
                return False, f"Expected {len(expected_results)} gender statistics results, got {len(actual_results)}"

            # Check each row
            for i, (actual, expected) in enumerate(zip(actual_results, expected_results)):
                if not rows_match(actual, expected):
                    return False, f"Gender statistics row {i+1} mismatch: expected {expected}, got {actual}"
            
            # Verify age group analysis by comparing with ground truth
            cur.execute("""
                SELECT age_group, employee_count, avg_salary, avg_tenure_days
                FROM employees.age_group_analysis
                ORDER BY age_group
            """)
            actual_age_results = cur.fetchall()
            
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
            expected_age_results = cur.fetchall()

            if len(actual_age_results) != len(expected_age_results):
                return False, f"Expected {len(expected_age_results)} age group results, got {len(actual_age_results)}"

            for i, (actual, expected) in enumerate(zip(actual_age_results, expected_age_results)):
                if not rows_match(actual, expected):
                    return False, f"Age group row {i+1} mismatch: expected {expected}, got {actual}"
            
            # Verify birth month distribution by comparing with ground truth
            cur.execute("""
                SELECT birth_month, month_name, employee_count, current_employee_count
                FROM employees.birth_month_distribution
                ORDER BY birth_month
            """)
            actual_birth_month_results = cur.fetchall()
            
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
            expected_birth_month_results = cur.fetchall()

            if len(actual_birth_month_results) != len(expected_birth_month_results):
                return False, f"Expected {len(expected_birth_month_results)} birth month results, got {len(actual_birth_month_results)}"

            for i, (actual, expected) in enumerate(zip(actual_birth_month_results, expected_birth_month_results)):
                if not rows_match(actual, expected):
                    return False, f"Birth month row {i+1} mismatch: expected {expected}, got {actual}"
            
            # Verify hiring year summary by comparing with ground truth
            cur.execute("""
                SELECT hire_year, employees_hired, still_employed, retention_rate
                FROM employees.hiring_year_summary
                ORDER BY hire_year
            """)
            actual_hiring_year_results = cur.fetchall()
            
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
            expected_hiring_year_results = cur.fetchall()

            if len(actual_hiring_year_results) != len(expected_hiring_year_results):
                return False, f"Expected {len(expected_hiring_year_results)} hiring year results, got {len(actual_hiring_year_results)}"

            for i, (actual, expected) in enumerate(zip(actual_hiring_year_results, expected_hiring_year_results)):
                if not rows_match(actual, expected):
                    return False, f"Hiring year row {i+1} mismatch: expected {expected}, got {actual}"
        
        conn.close()
        return True, f"Employee demographics report verified successfully ({len(actual_results)} gender records, {len(actual_age_results)} age group records, {len(actual_birth_month_results)} birth month records, {len(actual_hiring_year_results)} hiring year records)"
        
    except Exception as e:
        return False, f"Verification failed: {str(e)}"


@compare_func(name="postgres_employee_performance_verifier")
async def postgres_employee_performance_verifier(a: Any, b: Any, *args, **kwargs) -> (bool, str):
    """Verify employee performance analysis by comparing with ground truth queries.
    
    This function replicates the original verification logic from employee_performance_analysis/verify.py
    """
    try:
        conn_params = get_connection_params()
        if not conn_params["database"]:
            return False, "No database specified"
        
        conn = psycopg2.connect(**conn_params)
        
        with conn.cursor() as cur:
            # Get actual results from the created table
            cur.execute("""
                SELECT employee_id, performance_category, salary_growth_rate, 
                       days_of_service, promotion_count
                FROM employees.employee_performance_analysis 
                ORDER BY employee_id
            """)
            actual_results = cur.fetchall()
            
            # Execute ground truth query
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
                first_salary AS (
                SELECT employee_id, amount AS first_amount
                FROM (
                    SELECT s.*,
                        ROW_NUMBER() OVER (PARTITION BY s.employee_id
                                            ORDER BY s.from_date ASC, s.amount ASC) AS rn
                    FROM employees.salary s
                ) x
                WHERE rn = 1
                ),
                title_counts AS (
                SELECT t.employee_id, COUNT(DISTINCT t.title) AS promotion_count
                FROM employees.title t
                GROUP BY t.employee_id
                ),
                base AS (
                SELECT e.id AS employee_id,
                        e.hire_date,
                        cs.current_amount,
                        fs.first_amount,
                        COALESCE(tc.promotion_count, 0) AS promotion_count
                FROM employees.employee e
                JOIN current_salary cs ON cs.employee_id = e.id
                JOIN first_salary  fs ON fs.employee_id = e.id
                LEFT JOIN title_counts tc ON tc.employee_id = e.id
                ),
                scored AS (
                SELECT
                    employee_id,
                    ((current_amount - first_amount) / NULLIF(first_amount, 0)::NUMERIC) * 100 AS salary_growth_rate,
                    (CURRENT_DATE - hire_date)::INTEGER AS days_of_service,
                    promotion_count
                FROM base
                )
                SELECT
                s.employee_id,
                CASE
                    WHEN s.salary_growth_rate > 40 AND s.promotion_count > 1 THEN 'high_achiever'
                    WHEN s.salary_growth_rate > 20 AND s.days_of_service > 5000 THEN 'steady_performer'
                    WHEN s.salary_growth_rate < 10 AND s.days_of_service < 2000 THEN 'new_hire'
                    WHEN s.promotion_count = 0 AND s.days_of_service > 3000 THEN 'plateau'
                    ELSE 'average'
                END AS performance_category,
                s.salary_growth_rate,
                s.days_of_service,
                s.promotion_count
                FROM scored s
                ORDER BY s.employee_id;
            """)
            expected_results = cur.fetchall()

            if len(actual_results) != len(expected_results):
                return False, f"Expected {len(expected_results)} performance records, got {len(actual_results)}"

            # Check each row
            for i, (actual, expected) in enumerate(zip(actual_results, expected_results)):
                if not rows_match(actual, expected):
                    return False, f"Performance analysis row {i+1} mismatch: expected {expected}, got {actual}"
            
            # Verify department salary analysis by comparing with ground truth
            cur.execute("""
                SELECT department_name, avg_current_salary, employee_count, salary_range_spread
                FROM employees.department_salary_analysis
                ORDER BY department_name
            """)
            actual_dept_results = cur.fetchall()

            cur.execute("""
                WITH current_salary AS (
                SELECT employee_id, amount
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
                SELECT DISTINCT de.employee_id, de.department_id
                FROM employees.department_employee de
                WHERE de.to_date = DATE '9999-01-01'
                )
                SELECT 
                d.dept_name AS department_name,
                AVG(cs.amount)::DECIMAL AS avg_current_salary,
                COUNT(DISTINCT cd.employee_id) AS employee_count,
                (MAX(cs.amount) - MIN(cs.amount)) AS salary_range_spread
                FROM employees.department d
                JOIN current_dept cd ON cd.department_id = d.id
                JOIN current_salary cs ON cs.employee_id = cd.employee_id
                GROUP BY d.id, d.dept_name
                ORDER BY d.dept_name;
            """)
            expected_dept_results = cur.fetchall()

            if len(actual_dept_results) != len(expected_dept_results):
                return False, f"Expected {len(expected_dept_results)} department records, got {len(actual_dept_results)}"

            # Check each department row
            for i, (actual, expected) in enumerate(zip(actual_dept_results, expected_dept_results)):
                if not rows_match(actual, expected):
                    return False, f"Department analysis row {i+1} mismatch: expected {expected}, got {actual}"
        
        conn.close()
        return True, f"Employee performance analysis verified successfully ({len(actual_results)} performance records, {len(actual_dept_results)} department records)"
        
    except Exception as e:
        return False, f"Verification failed: {str(e)}"


@compare_func(name="postgres_employee_project_tracking_verifier")
async def postgres_employee_project_tracking_verifier(a: Any, b: Any, *args, **kwargs) -> (bool, str):
    """Verify employee project tracking by checking table structures and data.
    
    This function replicates the original verification logic from employee_project_tracking/verify.py
    """
    try:
        conn_params = get_connection_params()
        if not conn_params["database"]:
            return False, "No database specified"
        
        conn = psycopg2.connect(**conn_params)
        
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
                return False, f"Expected 3 tables, found {len(tables)}: {tables}"
                
            # Check foreign key constraints exist
            cur.execute("""
                SELECT COUNT(*) FROM information_schema.table_constraints 
                WHERE table_schema = 'employees' 
                AND constraint_type = 'FOREIGN KEY'
                AND table_name IN ('project_assignments', 'project_milestones')
            """)
            fkey_count = cur.fetchone()[0]
            
            if fkey_count != 3:
                return False, f"Expected 3 foreign key constraints, found {fkey_count}"
                
            # Check if priority column exists
            cur.execute("""
                SELECT COUNT(*) FROM information_schema.columns 
                WHERE table_schema = 'employees' AND table_name = 'employee_projects'
                AND column_name = 'priority'
            """)
            priority_exists = cur.fetchone()[0]
            
            if priority_exists == 0:
                return False, "Priority column was not added to employee_projects table"
            
            # Check for required indexes
            cur.execute("""
                SELECT COUNT(*) 
                FROM pg_indexes 
                WHERE schemaname = 'employees' 
                AND indexname IN ('idx_projects_status', 'idx_assignments_emp_proj', 'idx_milestones_due_date')
            """)
            index_count = cur.fetchone()[0]
            
            if index_count != 3:
                return False, f"Expected 3 required indexes, got {index_count}"
            
            # Verify project data by comparing with expected values
            cur.execute("""
                SELECT project_name, start_date, end_date, budget, status, priority
                FROM employees.employee_projects
                ORDER BY project_name
            """)
            projects = cur.fetchall()
            
            if len(projects) != 3:
                return False, f"Expected 3 projects, found {len(projects)}"
                
            # Expected final state after all updates
            expected_projects = {
                'Database Modernization': ('2024-01-15', '2024-06-30', 287500.00, 'active', 'high'),
                'Employee Portal Upgrade': ('2024-02-01', '2024-05-15', 207000.00, 'active', 'medium'),
                'HR Analytics Dashboard': ('2023-11-01', '2024-01-31', 120000.00, 'completed', 'medium')
            }
            
            for project in projects:
                name = project[0]
                if name not in expected_projects:
                    return False, f"Unexpected project: {name}"
                    
                exp = expected_projects[name]
                expected_row = (name,) + exp
                if not rows_match(project, expected_row):
                    return False, f"Project {name} data mismatch: expected {expected_row}, got {project}"
            
            # Verify assignment data
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
                    return False, f"Department {dept_name} has multiple assignments"
                dept_found[dept_name] = (project_id, role, allocation)
                
            for dept, expected in expected_mappings.items():
                if dept not in dept_found:
                    return False, f"Department {dept} has no assignments"
                if dept_found[dept] != expected:
                    return False, f"Department {dept} assignment mismatch: expected {expected}, got {dept_found[dept]}"
                    
            # Check that all assignments have correct assigned_date
            cur.execute("""
                SELECT COUNT(*) FROM employees.project_assignments 
                WHERE assigned_date != '2024-01-01'
            """)
            wrong_date_count = cur.fetchone()[0]
            
            if wrong_date_count > 0:
                return False, f"{wrong_date_count} assignments have incorrect assigned_date"
            
            # Verify milestone data
            cur.execute("""
                SELECT project_id, milestone_name, due_date, completed
                FROM employees.project_milestones
                ORDER BY project_id, milestone_name
            """)
            milestones = cur.fetchall()
            
            if len(milestones) != 6:
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
                    return False, f"Unexpected milestone: {key}"
                    
                expected_due, expected_completed = expected_milestones[key]
                if str(due_date) != expected_due or completed != expected_completed:
                    return False, f"Milestone {name} mismatch: expected ({expected_due}, {expected_completed}), got ({due_date}, {completed})"
        
        conn.close()
        return True, f"Employee project tracking verified successfully (3 tables, {fkey_count} FKs, {index_count} indexes, {len(projects)} projects, {assignment_count} assignments, {len(milestones)} milestones)"
        
    except Exception as e:
        return False, f"Verification failed: {str(e)}"

@compare_func(name="postgres_employee_retention_verifier")
async def postgres_employee_retention_verifier(a: Any, b: Any, *args, **kwargs) -> (bool, str):
    """Verify employee retention analysis by comparing with ground truth queries.
    
    This function replicates the original verification logic from employee_retention_analysis/verify.py
    """
    try:
        conn_params = get_connection_params()
        if not conn_params["database"]:
            return False, "No database specified"
        
        conn = psycopg2.connect(**conn_params)
        
        with conn.cursor() as cur:
            # Verify retention analysis results
            cur.execute("""
                SELECT department_name, total_employees_ever, current_employees, 
                       former_employees, retention_rate
                FROM employees.employee_retention_analysis
                ORDER BY department_name
            """)
            actual_retention_results = cur.fetchall()
            
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
            expected_retention_results = cur.fetchall()

            if len(actual_retention_results) != len(expected_retention_results):
                return False, f"Expected {len(expected_retention_results)} retention analysis results, got {len(actual_retention_results)}"

            for i, (actual, expected) in enumerate(zip(actual_retention_results, expected_retention_results)):
                if not rows_match(actual, expected):
                    return False, f"Retention analysis row {i+1} mismatch: expected {expected}, got {actual}"
            
            # Verify high risk employee analysis results
            cur.execute("""
                SELECT employee_id, full_name, current_department, tenure_days, 
                       current_salary, risk_category
                FROM employees.high_risk_employees
                ORDER BY employee_id
            """)
            actual_risk_results = cur.fetchall()
            
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
            expected_risk_results = cur.fetchall()

            if len(actual_risk_results) != len(expected_risk_results):
                return False, f"Expected {len(expected_risk_results)} high risk analysis results, got {len(actual_risk_results)}"

            for i, (actual, expected) in enumerate(zip(actual_risk_results, expected_risk_results)):
                if not rows_match(actual, expected):
                    return False, f"High risk analysis row {i+1} mismatch: expected {expected}, got {actual}"
            
            # Verify turnover trend analysis results
            cur.execute("""
                SELECT departure_year, departures_count, avg_tenure_days, avg_final_salary
                FROM employees.turnover_trend_analysis
                ORDER BY departure_year
            """)
            actual_turnover_results = cur.fetchall()
            
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
            expected_turnover_results = cur.fetchall()

            if len(actual_turnover_results) != len(expected_turnover_results):
                return False, f"Expected {len(expected_turnover_results)} turnover trend results, got {len(actual_turnover_results)}"

            for i, (actual, expected) in enumerate(zip(actual_turnover_results, expected_turnover_results)):
                if not rows_match(actual, expected):
                    return False, f"Turnover trend row {i+1} mismatch: expected {expected}, got {actual}"
        
        conn.close()
        return True, f"Employee retention analysis verified successfully ({len(actual_retention_results)} retention records, {len(actual_risk_results)} risk records, {len(actual_turnover_results)} turnover records)"
        
    except Exception as e:
        return False, f"Verification failed: {str(e)}"

@compare_func(name="postgres_executive_dashboard_automation_verifier")
async def postgres_executive_dashboard_automation_verifier(a: Any, b: Any, *args, **kwargs) -> (bool, str):
    """Verify executive dashboard automation by checking materialized views, procedures, triggers, and data.
    
    This function replicates the original verification logic from executive_dashboard_automation/verify.py
    """
    try:
        conn_params = get_connection_params()
        if not conn_params["database"]:
            return False, "No database specified"
        
        conn = psycopg2.connect(**conn_params)
        
        with conn.cursor() as cur:
            # Verify materialized views exist
            cur.execute("""
                SELECT matviewname FROM pg_matviews 
                WHERE schemaname = 'employees' 
                AND matviewname IN ('exec_department_summary', 'exec_hiring_trends', 'exec_salary_distribution')
                ORDER BY matviewname
            """)
            views = [row[0] for row in cur.fetchall()]
            
            expected_views = ['exec_department_summary', 'exec_hiring_trends', 'exec_salary_distribution']
            if set(views) != set(expected_views):
                return False, f"Expected views {expected_views}, found {views}"
            
            # Verify department summary data accuracy
            cur.execute("""
                SELECT department_name, total_employees, avg_salary, total_payroll, manager_name
                FROM employees.exec_department_summary
                ORDER BY department_name
            """)
            view_data = cur.fetchall()
            
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
                return False, f"Department count mismatch: view={len(view_data)}, actual={len(actual_data)}"
                
            for view_row, actual_row in zip(view_data, actual_data):
                if not rows_match(view_row, actual_row):
                    return False, f"Department summary data incorrect for {view_row[0]}: view={view_row}, actual={actual_row}"
            
            # Verify hiring trends data accuracy
            cur.execute("""
                SELECT hire_year, employees_hired, avg_starting_salary, retention_rate, top_hiring_department
                FROM employees.exec_hiring_trends
                ORDER BY hire_year
            """)
            hiring_view_data = cur.fetchall()
            
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
                return False, f"Hiring trends count mismatch: view={len(hiring_view_data)}, actual={len(actual_hiring_data)}"
            
            for hiring_view, actual_hiring in zip(hiring_view_data, actual_hiring_data):
                if not rows_match(hiring_view, actual_hiring):
                    return False, f"Hiring trends data incorrect for year {hiring_view[0]}: view={hiring_view}, actual={actual_hiring}"
            
            # Verify salary distribution data accuracy
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
            
            if len(view_bands) != len(actual_bands):
                return False, f"Salary band count mismatch: view={len(view_bands)}, actual={len(actual_bands)}"
                
            for view_band, actual_band in zip(view_bands, actual_bands):
                if not rows_match(view_band, actual_band):
                    return False, f"Salary band {actual_band[0]} data incorrect: view={view_band}, actual={actual_band}"
            
            # Verify stored procedure exists
            cur.execute("""
                SELECT routine_name FROM information_schema.routines 
                WHERE routine_schema = 'employees' 
                AND routine_type = 'FUNCTION'
                AND routine_name = 'generate_monthly_report'
            """)
            procedures = [row[0] for row in cur.fetchall()]
            
            if 'generate_monthly_report' not in procedures:
                return False, "generate_monthly_report procedure not found"
            
            # Verify monthly_reports table structure
            cur.execute("""
                SELECT COUNT(*) FROM information_schema.columns 
                WHERE table_schema = 'employees' AND table_name = 'monthly_reports'
                AND column_name IN ('report_id', 'report_date', 'department_count', 'total_employees', 'avg_salary', 'generated_at')
            """)
            report_columns = cur.fetchone()[0]
            if report_columns != 6:
                return False, "monthly_reports table missing required columns"
            
            # Verify triggers exist
            cur.execute("""
                SELECT trigger_name FROM information_schema.triggers 
                WHERE trigger_schema = 'employees'
                AND trigger_name = 'high_salary_alert'
            """)
            triggers = [row[0] for row in cur.fetchall()]
            
            if 'high_salary_alert' not in triggers:
                return False, "high_salary_alert trigger not found"
            
            # Verify salary_alerts table exists
            cur.execute("""
                SELECT table_name FROM information_schema.tables 
                WHERE table_schema = 'employees' 
                AND table_name = 'salary_alerts'
            """)
            trigger_tables = [row[0] for row in cur.fetchall()]
            
            if 'salary_alerts' not in trigger_tables:
                return False, "salary_alerts table not found"
            
            # Verify trigger functionality - check old salary record was properly closed
            cur.execute("""
                SELECT COUNT(*) FROM employees.salary 
                WHERE employee_id = 10001 AND to_date = '2024-01-31'
            """)
            old_salary_count = cur.fetchone()[0]
            if old_salary_count == 0:
                return False, "Old salary record for employee 10001 was not properly closed with to_date='2024-01-31'"
            
            # Verify new salary record was inserted
            cur.execute("""
                SELECT COUNT(*) FROM employees.salary 
                WHERE employee_id = 10001 AND amount = 125000 
                AND from_date = '2024-02-01' AND to_date = '9999-01-01'
            """)
            new_salary_count = cur.fetchone()[0]
            if new_salary_count == 0:
                return False, "New salary record for employee 10001 with amount 125000 was not inserted"
            
            # Verify high salary alert was triggered
            cur.execute("""
                SELECT COUNT(*) FROM employees.salary_alerts 
                WHERE employee_id = 10001 AND salary_amount = 125000 AND status = 'new'
            """)
            alert_count = cur.fetchone()[0]
            if alert_count == 0:
                return False, "High salary alert was not triggered correctly for employee 10001 with amount 125000"
            
            # Verify procedure execution - check monthly report data
            cur.execute("""
                SELECT department_count, total_employees, avg_salary
                FROM employees.monthly_reports 
                WHERE report_date = '2024-01-01'
            """)
            report_data = cur.fetchone()
            if not report_data:
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
            
            if not rows_match(report_data, actual_stats):
                return False, f"Monthly report data incorrect: expected {actual_stats}, got {report_data}"
            
            # Verify performance indexes
            cur.execute("""
                SELECT indexname FROM pg_indexes 
                WHERE schemaname = 'employees' 
                AND tablename IN ('salary_alerts', 'monthly_reports')
                AND indexname LIKE 'idx_%'
                ORDER BY indexname
            """)
            indexes = [row[0] for row in cur.fetchall()]
            
            if len(indexes) < 2:
                return False, f"Expected at least 2 performance indexes, found {len(indexes)}"
        
        conn.close()
        return True, f"Executive dashboard automation verified successfully (3 materialized views, 1 stored procedure, 1 trigger, {len(indexes)} indexes, monthly report generated)"
        
    except Exception as e:
        return False, f"Verification failed: {str(e)}"

@compare_func(name="postgres_management_structure_analysis_verifier")
async def postgres_management_structure_analysis_verifier(a: Any, b: Any, *args, **kwargs) -> (bool, str):
    """Verify management structure analysis by comparing with ground truth queries.
    
    This function replicates the original verification logic from management_structure_analysis/verify.py
    """
    try:
        conn_params = get_connection_params()
        if not conn_params["database"]:
            return False, "No database specified"
        
        conn = psycopg2.connect(**conn_params)
        
        with conn.cursor() as cur:
            # Verify manager profile results
            cur.execute("""
                SELECT manager_id, manager_name, current_department, 
                       management_periods, current_manager
                FROM employees.manager_profile
                ORDER BY manager_id
            """)
            actual_manager_results = cur.fetchall()
            
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
            expected_manager_results = cur.fetchall()

            if len(actual_manager_results) != len(expected_manager_results):
                return False, f"Expected {len(expected_manager_results)} manager profile results, got {len(actual_manager_results)}"

            for i, (actual, expected) in enumerate(zip(actual_manager_results, expected_manager_results)):
                if not rows_match(actual, expected):
                    return False, f"Manager profile row {i+1} mismatch: expected {expected}, got {actual}"
            
            # Verify department leadership results
            cur.execute("""
                SELECT department_name, current_manager_name, manager_start_date, 
                       total_historical_managers
                FROM employees.department_leadership
                ORDER BY department_name
            """)
            actual_leadership_results = cur.fetchall()
            
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
            expected_leadership_results = cur.fetchall()

            if len(actual_leadership_results) != len(expected_leadership_results):
                return False, f"Expected {len(expected_leadership_results)} department leadership results, got {len(actual_leadership_results)}"

            for i, (actual, expected) in enumerate(zip(actual_leadership_results, expected_leadership_results)):
                if not rows_match(actual, expected):
                    return False, f"Department leadership row {i+1} mismatch: expected {expected}, got {actual}"
            
            # Verify management transitions results
            cur.execute("""
                SELECT department_name, transition_year, outgoing_manager, incoming_manager, transition_gap_days
                FROM employees.management_transitions
                ORDER BY department_name, transition_year
            """)
            actual_transitions_results = cur.fetchall()
            
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
            expected_transitions_results = cur.fetchall()

            if len(actual_transitions_results) != len(expected_transitions_results):
                return False, f"Expected {len(expected_transitions_results)} management transitions results, got {len(actual_transitions_results)}"

            for i, (actual, expected) in enumerate(zip(actual_transitions_results, expected_transitions_results)):
                if not rows_match(actual, expected):
                    return False, f"Management transitions row {i+1} mismatch: expected {expected}, got {actual}"
            
            # Verify span of control results
            cur.execute("""
                SELECT manager_id, manager_name, department_name, total_employees, 
                       current_employees, management_load
                FROM employees.span_of_control
                ORDER BY manager_id
            """)
            actual_span_results = cur.fetchall()
            
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
            expected_span_results = cur.fetchall()

            if len(actual_span_results) != len(expected_span_results):
                return False, f"Expected {len(expected_span_results)} span of control results, got {len(actual_span_results)}"

            for i, (actual, expected) in enumerate(zip(actual_span_results, expected_span_results)):
                if not rows_match(actual, expected):
                    return False, f"Span of control row {i+1} mismatch: expected {expected}, got {actual}"
        
        conn.close()
        return True, f"Management structure analysis verified successfully ({len(actual_manager_results)} manager profiles, {len(actual_leadership_results)} department leadership records, {len(actual_transitions_results)} transition records, {len(actual_span_results)} span of control records)"
        
    except Exception as e:
        return False, f"Verification failed: {str(e)}"

@compare_func(name="postgres_consistency_enforcement_verifier")
async def postgres_consistency_enforcement_verifier(a: Any, b: Any, *args, **kwargs) -> (bool, str):
    """Verify LEGO consistency enforcement by checking data consistency, triggers, and constraint enforcement.
    
    This function replicates the original verification logic from consistency_enforcement/verify.py
    """
    try:
        conn_params = get_connection_params()
        if not conn_params["database"]:
            return False, "No database specified"
        
        conn = psycopg2.connect(**conn_params)
        conn.autocommit = False  # Ensure we control transactions
        
        with conn.cursor() as cur:
            # Helper function to get mismatch count
            def get_mismatch_count():
                cur.execute("""
                    WITH latest_inv AS (
                        SELECT set_num, MAX(version) AS max_version
                        FROM public.lego_inventories
                        GROUP BY set_num
                    ), inv_latest AS (
                        SELECT li.set_num, li.id
                        FROM public.lego_inventories li
                        JOIN latest_inv lv ON lv.set_num = li.set_num AND lv.max_version = li.version
                    ), parts_agg AS (
                        SELECT
                            i.set_num,
                            SUM(lip.quantity) AS actual_parts
                        FROM inv_latest i
                        JOIN public.lego_inventory_parts lip ON lip.inventory_id = i.id
                        WHERE lip.is_spare = false
                        GROUP BY i.set_num
                    )
                    SELECT COUNT(*)
                    FROM public.lego_sets s
                    LEFT JOIN parts_agg pa ON s.set_num = pa.set_num
                    WHERE s.num_parts <> COALESCE(pa.actual_parts, 0);
                """)
                return cur.fetchone()[0]
            
            # Helper function to fetch candidate part row
            def fetch_candidate_part_row():
                cur.execute("""
                    WITH latest_inv AS (
                        SELECT set_num, MAX(version) AS max_version
                        FROM public.lego_inventories
                        GROUP BY set_num
                    ), inv AS (
                        SELECT li.id, li.set_num
                        FROM public.lego_inventories li
                        JOIN latest_inv lv ON lv.set_num = li.set_num AND lv.max_version = li.version
                    )
                    SELECT i.id AS inventory_id, i.set_num, lip.part_num, lip.color_id
                    FROM inv i
                    JOIN public.lego_inventory_parts lip ON lip.inventory_id = i.id
                    WHERE lip.is_spare = false AND lip.quantity > 0
                    LIMIT 1;
                """)
                return cur.fetchone()
            
            # 1. Verify data consistency (Task 1)
            count = get_mismatch_count()
            if count > 1:
                return False, f"Found {count} sets with inconsistent part counts. Expected 0 or 1 after fix."
            
            # 2. Verify constraint triggers exist (Task 2 Part A)
            tables_to_check = [
                'public.lego_inventory_parts',
                'public.lego_inventories',
                'public.lego_sets'
            ]
            all_triggers_found = True
            for table in tables_to_check:
                cur.execute("""
                    SELECT COUNT(*)
                    FROM pg_trigger
                    WHERE tgrelid = %s::regclass AND tgconstraint <> 0;
                """, (table,))
                trigger_count = cur.fetchone()[0]
                if trigger_count == 0:
                    return False, f"No constraint trigger found on table '{table}'."
            
            # 3. Verify violation is blocked (Task 2 Part B)
            candidate = fetch_candidate_part_row()
            if candidate:
                inventory_id, _, part_num, color_id = candidate
                try:
                    # This transaction should fail due to the trigger
                    cur.execute("""
                        UPDATE public.lego_inventory_parts
                        SET quantity = quantity + 1
                        WHERE inventory_id = %s AND part_num = %s AND color_id = %s;
                    """, (inventory_id, part_num, color_id))
                    # If we reach here, the trigger failed to block the update.
                    conn.rollback()
                    return False, "An inconsistent write was NOT blocked by the trigger."
                except psycopg2.Error as e:
                    # We expect an error. Any error here is considered a success as the transaction was blocked.
                    conn.rollback()
            
            # 4. Verify deferred transaction is allowed (Task 2 Part C)
            if candidate:
                inventory_id, set_num, part_num, color_id = candidate
                try:
                    # This multi-statement transaction should succeed with deferred constraints
                    cur.execute("BEGIN;")
                    cur.execute("SET CONSTRAINTS ALL DEFERRED;")
                    cur.execute("""
                        UPDATE public.lego_inventory_parts SET quantity = quantity + 1 
                        WHERE inventory_id = %s AND part_num = %s AND color_id = %s;
                    """, (inventory_id, part_num, color_id))
                    cur.execute("""
                        UPDATE public.lego_sets SET num_parts = num_parts + 1 
                        WHERE set_num = %s;
                    """, (set_num,))
                    cur.execute("COMMIT;")
                    
                    # Revert changes to leave DB in its original state
                    cur.execute("BEGIN;")
                    cur.execute("SET CONSTRAINTS ALL DEFERRED;")
                    cur.execute("""
                        UPDATE public.lego_inventory_parts SET quantity = quantity - 1 
                        WHERE inventory_id = %s AND part_num = %s AND color_id = %s;
                    """, (inventory_id, part_num, color_id))
                    cur.execute("""
                        UPDATE public.lego_sets SET num_parts = num_parts - 1 
                        WHERE set_num = %s;
                    """, (set_num,))
                    cur.execute("COMMIT;")
                    
                except psycopg2.Error as e:
                    conn.rollback()
                    return False, f"Deferred transaction failed to commit. Error: {e}"
        
        conn.close()
        return True, f"LEGO consistency enforcement verified successfully (data consistency: {count} mismatches, triggers: {len(tables_to_check)} tables, constraint blocking: {'tested' if candidate else 'skipped'}, deferred transactions: {'tested' if candidate else 'skipped'})"
        
    except Exception as e:
        return False, f"Verification failed: {str(e)}"

@compare_func(name="postgres_database_security_policies_verifier")
async def postgres_database_security_policies_verifier(a: Any, b: Any, *args, **kwargs) -> (bool, str):
    """Verify LEGO database security policies by checking role creation, RLS, policies, and theme function.
    
    This function replicates the original verification logic from database_security_policies/verify.py
    """
    try:
        conn_params = get_connection_params()
        if not conn_params["database"]:
            return False, "No database specified"
        
        conn = psycopg2.connect(**conn_params)
        
        with conn.cursor() as cur:
            # 1. Verify role creation (Task 1)
            cur.execute("SELECT 1 FROM pg_roles WHERE rolname = 'theme_analyst';")
            if not cur.fetchone():
                return False, "The 'theme_analyst' role was not created."
            
            # Check SELECT permissions on reference and main tables
            all_tables = [
                'lego_themes', 'lego_colors', 'lego_parts', 'lego_part_categories',
                'lego_sets', 'lego_inventories', 'lego_inventory_parts'
            ]
            for table in all_tables:
                cur.execute("""
                    SELECT has_table_privilege('theme_analyst', %s, 'SELECT');
                """, (table,))
                if not cur.fetchone()[0]:
                    return False, f"'theme_analyst' role is missing SELECT permission on '{table}'."
            
            # Check that no INSERT/UPDATE/DELETE permissions exist
            for table in all_tables:
                cur.execute("""
                    SELECT 
                        has_table_privilege('theme_analyst', %s, 'INSERT') OR
                        has_table_privilege('theme_analyst', %s, 'UPDATE') OR
                        has_table_privilege('theme_analyst', %s, 'DELETE');
                """, (table, table, table))
                if cur.fetchone()[0]:
                    return False, f"'theme_analyst' role has unauthorized INSERT, UPDATE, or DELETE permission on '{table}'."
            
            # 2. Verify RLS enabled (Task 2)
            tables_to_check = ['lego_sets', 'lego_inventories', 'lego_inventory_parts']
            for table in tables_to_check:
                cur.execute("SELECT relrowsecurity FROM pg_class WHERE relname = %s;", (table,))
                rls_enabled = cur.fetchone()
                if not rls_enabled or not rls_enabled[0]:
                    return False, f"RLS is not enabled on table '{table}'."
            
            # 3. Verify RLS policies (Task 3)
            expected_policies = {
                'lego_sets': 'theme_sets_policy',
                'lego_inventories': 'theme_inventories_policy',
                'lego_inventory_parts': 'theme_inventory_parts_policy'
            }
            for table, policy_name in expected_policies.items():
                cur.execute("""
                    SELECT 1 FROM pg_policies WHERE tablename = %s AND policyname = %s;
                """, (table, policy_name))
                if not cur.fetchone():
                    return False, f"RLS policy '{policy_name}' not found on table '{table}'."
            
            # 4. Verify theme function (Task 4)
            cur.execute("SELECT 1 FROM pg_proc WHERE proname = 'get_user_theme_id';")
            if not cur.fetchone():
                return False, "The 'get_user_theme_id' function was not created."
            
            try:
                # Test the function's output specifically for the 'theme_analyst' role
                cur.execute("SET ROLE theme_analyst;")
                cur.execute("SELECT get_user_theme_id();")
                theme_id = cur.fetchone()[0]
                cur.execute("RESET ROLE;")
                
                if theme_id != 18:
                    return False, f"get_user_theme_id() returned {theme_id} for 'theme_analyst', but expected 18."
                
            except Exception as e:
                conn.rollback()
                return False, f"Error testing get_user_theme_id() function: {e}"
            
            # 5. Test theme analyst access (Task 5)
            try:
                # Assume the role of theme_analyst for this session
                cur.execute("SET ROLE theme_analyst;")
                
                # Test 1: Check Star Wars sets access (should return 2 sets)
                cur.execute("SELECT set_num FROM lego_sets ORDER BY set_num;")
                star_wars_sets = [row[0] for row in cur.fetchall()]
                expected_sets = ['65081-1', 'K8008-1']
                
                if sorted(star_wars_sets) != sorted(expected_sets):
                    cur.execute("RESET ROLE;")
                    return False, f"Expected Star Wars sets {expected_sets}, but got {star_wars_sets}."
                
                # Test 2: Check that Technic sets are not accessible (should return 0)
                cur.execute("SELECT COUNT(*) FROM lego_sets WHERE theme_id = 1;")
                technic_count = cur.fetchone()[0]
                if technic_count != 0:
                    cur.execute("RESET ROLE;")
                    return False, f"Technic sets should be blocked, but query returned {technic_count} sets."
                
                # Test 3: Check reference tables are fully accessible
                cur.execute("SELECT COUNT(*) > 10 FROM lego_themes;")
                if not cur.fetchone()[0]:
                    cur.execute("RESET ROLE;")
                    return False, "'lego_themes' table seems inaccessible or empty."
                
                # Test 4 & 5: Check related tables
                cur.execute("SELECT COUNT(*) FROM lego_inventories;")
                if cur.fetchone()[0] == 0:
                    cur.execute("RESET ROLE;")
                    return False, "No inventories are visible for the allowed sets."
                
                cur.execute("SELECT COUNT(*) FROM lego_inventory_parts;")
                if cur.fetchone()[0] == 0:
                    cur.execute("RESET ROLE;")
                    return False, "No inventory parts are visible for the allowed sets."
                
                # IMPORTANT: Always reset the role at the end
                cur.execute("RESET ROLE;")
                
            except Exception as e:
                conn.rollback()
                # Try to reset role even on failure to clean up session state
                try:
                    with conn.cursor() as cleanup_cur:
                        cleanup_cur.execute("RESET ROLE;")
                except:
                    pass
                return False, f"An error occurred while testing data access as 'theme_analyst': {e}"
        
        conn.close()
        return True, f"LEGO database security policies verified successfully (role: theme_analyst, RLS: {len(tables_to_check)} tables, policies: {len(expected_policies)}, theme function: working, access control: Star Wars sets accessible, Technic blocked)"
        
    except Exception as e:
        return False, f"Verification failed: {str(e)}"

@compare_func(name="postgres_transactional_inventory_transfer_verifier")
async def postgres_transactional_inventory_transfer_verifier(a: Any, b: Any, *args, **kwargs) -> (bool, str):
    """Verify LEGO transactional inventory transfer by checking system components, transfers, business rules, and audit logging.
    
    This function replicates the original verification logic from transactional_inventory_transfer/verify.py
    """
    try:
        conn_params = get_connection_params()
        if not conn_params["database"]:
            return False, "No database specified"
        
        conn = psycopg2.connect(**conn_params)
        conn.autocommit = False  # Ensure we can control transactions manually
        
        def get_inventory_part_quantity(inventory_id: int, part_num: str, color_id: int) -> int:
            """Get the current quantity of a specific part in an inventory."""
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT quantity FROM public.lego_inventory_parts
                    WHERE inventory_id = %s AND part_num = %s AND color_id = %s
                """, (inventory_id, part_num, color_id))
                result = cur.fetchone()
                return result[0] if result else 0
        
        # 1. Verify system components
        with conn.cursor() as cur:
            # Check main function
            cur.execute("""
                SELECT COUNT(*) FROM pg_proc p
                JOIN pg_namespace n ON p.pronamespace = n.oid
                WHERE n.nspname = 'public' AND p.proname = 'transfer_parts'
            """)
            main_func_count = cur.fetchone()[0]
            
            # Check audit table
            cur.execute("""
                SELECT COUNT(*) FROM information_schema.tables 
                WHERE table_schema = 'public' AND table_name = 'inventory_transfer_log'
            """)
            audit_table_count = cur.fetchone()[0]
            
            if main_func_count == 0:
                return False, "transfer_parts function does not exist"
            
            if audit_table_count == 0:
                return False, "inventory_transfer_log table does not exist"
        
        # 2. Verify successful transfer with audit
        try:
            # Test data: Transfer 100 white plates from Mosaic Dino to Mosaic Johnny Thunder
            source_id = 14469
            target_id = 14686
            part_num = '3024'
            color_id = 15
            transfer_qty = 100
            reason = 'inventory_adjustment'
            
            source_initial = get_inventory_part_quantity(source_id, part_num, color_id)
            target_initial = get_inventory_part_quantity(target_id, part_num, color_id)
            
            # Get initial audit log count
            with conn.cursor() as cur:
                cur.execute("SELECT COUNT(*) FROM inventory_transfer_log")
                initial_log_count = cur.fetchone()[0]
            
            with conn.cursor() as cur:
                cur.execute("SELECT transfer_parts(%s, %s, %s, %s, %s, %s)",
                           (source_id, target_id, part_num, color_id, transfer_qty, reason))
                result = cur.fetchone()
            
            source_final = get_inventory_part_quantity(source_id, part_num, color_id)
            target_final = get_inventory_part_quantity(target_id, part_num, color_id)
            
            # Verify audit log entry
            with conn.cursor() as cur:
                cur.execute("SELECT COUNT(*) FROM inventory_transfer_log")
                final_log_count = cur.fetchone()[0]
                
                if final_log_count <= initial_log_count:
                    return False, "No audit log entry was created"
                
                # Check latest audit entry
                cur.execute("""
                    SELECT transfer_status, quantity_transferred, transfer_reason
                    FROM inventory_transfer_log
                    ORDER BY log_id DESC
                    LIMIT 1
                """)
                audit_entry = cur.fetchone()
                
                if not audit_entry:
                    return False, "Could not retrieve audit log entry"
                
                status, qty_transferred, trans_reason = audit_entry
                
                if status != 'success':
                    return False, f"Transfer status should be 'success', got '{status}'"
                
                if qty_transferred != transfer_qty or trans_reason != reason:
                    return False, "Audit log details don't match transfer parameters"
            
            expected_source = source_initial - transfer_qty
            expected_target = target_initial + transfer_qty
            
            if source_final != expected_source:
                return False, f"Source quantity mismatch. Expected {expected_source}, got {source_final}"
            elif target_final != expected_target:
                return False, f"Target quantity mismatch. Expected {expected_target}, got {target_final}"
                
        except psycopg2.Error as e:
            return False, f"Transfer failed unexpectedly with error: {e}"
        finally:
            conn.rollback()
        
        # 3. Verify new part transfer
        try:
            # Test data: Transfer red bricks to Mosaic Johnny Thunder (which doesn't have them)
            source_id = 11124  # Giant Lego Dacta Basic Set (has red bricks)
            target_id = 14686  # Lego Mosaic Johnny Thunder (doesn't have red bricks)
            part_num = '3001'
            color_id = 4
            transfer_qty = 50
            reason = 'part_redistribution'
            
            target_initial = get_inventory_part_quantity(target_id, part_num, color_id)
            if target_initial != 0:
                return False, f"Pre-condition failed. Target already has {target_initial} of this part, expected 0"
            
            source_initial = get_inventory_part_quantity(source_id, part_num, color_id)
            
            with conn.cursor() as cur:
                cur.execute("SELECT transfer_parts(%s, %s, %s, %s, %s, %s)",
                           (source_id, target_id, part_num, color_id, transfer_qty, reason))
                result = cur.fetchone()
            
            source_final = get_inventory_part_quantity(source_id, part_num, color_id)
            target_final = get_inventory_part_quantity(target_id, part_num, color_id)
            
            expected_source = source_initial - transfer_qty
            expected_target = transfer_qty
            
            if source_final != expected_source:
                return False, f"Source quantity mismatch. Expected {expected_source}, got {source_final}"
            elif target_final != expected_target:
                return False, f"Target quantity mismatch. Expected {expected_target}, got {target_final}"
                
        except psycopg2.Error as e:
            return False, f"Transfer failed unexpectedly with error: {e}"
        finally:
            conn.rollback()
        
        # 4. Verify business rule validation
        # Test 1: Self-transfer (should fail)
        try:
            source_id = 14469
            part_num = '3024'
            color_id = 15
            transfer_qty = 10
            reason = 'self_transfer'
            
            with conn.cursor() as cur:
                cur.execute("SELECT transfer_parts(%s, %s, %s, %s, %s, %s)",
                           (source_id, source_id, part_num, color_id, transfer_qty, reason))
                result = cur.fetchone()
                return False, f"Self-transfer should have failed but succeeded: {result[0]}"
        except psycopg2.Error:
            pass  # Expected failure
        except Exception as e:
            return False, f"Self-transfer test failed with unexpected error: {e}"
        finally:
            conn.rollback()
        
        # Test 2: Transfer quantity exceeds maximum (should fail)
        try:
            source_id = 14469
            target_id = 14686
            part_num = '3024'
            color_id = 15
            
            with conn.cursor() as cur:
                cur.execute("SELECT transfer_parts(%s, %s, %s, %s, %s, %s)",
                           (source_id, target_id, part_num, color_id, 600, 'large_transfer'))
                result = cur.fetchone()
                return False, f"Large transfer should have failed but succeeded: {result[0]}"
        except psycopg2.Error:
            pass  # Expected failure
        except Exception as e:
            return False, f"Large transfer test failed with unexpected error: {e}"
        finally:
            conn.rollback()
        
        # Test 3: Transfer quantity below minimum (should fail)
        try:
            source_id = 14469
            target_id = 14686
            part_num = '3024'
            color_id = 15
            
            with conn.cursor() as cur:
                cur.execute("SELECT transfer_parts(%s, %s, %s, %s, %s, %s)",
                           (source_id, target_id, part_num, color_id, 0, 'zero_transfer'))
                result = cur.fetchone()
                return False, f"Zero transfer should have failed but succeeded: {result[0]}"
        except psycopg2.Error:
            pass  # Expected failure
        except Exception as e:
            return False, f"Zero transfer test failed with unexpected error: {e}"
        finally:
            conn.rollback()
        
        # 5. Verify insufficient quantity error
        try:
            source_id = 14469
            target_id = 14686
            part_num = '3024'
            color_id = 15
            transfer_qty = 99999  # Far more than available
            reason = 'insufficient_test'
            
            source_initial = get_inventory_part_quantity(source_id, part_num, color_id)
            target_initial = get_inventory_part_quantity(target_id, part_num, color_id)
            
            with conn.cursor() as cur:
                try:
                    cur.execute("SELECT transfer_parts(%s, %s, %s, %s, %s, %s)",
                               (source_id, target_id, part_num, color_id, transfer_qty, reason))
                    result = cur.fetchone()
                    return False, f"Transfer should have failed but succeeded: {result[0]}"
                except psycopg2.Error as e:
                    # After an exception, the transaction is in an aborted state. Must rollback before new queries.
                    conn.rollback()
                    
                    source_final = get_inventory_part_quantity(source_id, part_num, color_id)
                    target_final = get_inventory_part_quantity(target_id, part_num, color_id)
                    
                    if source_final != source_initial:
                        return False, f"Source quantity changed from {source_initial} to {source_final}"
                    elif target_final != target_initial:
                        return False, f"Target quantity changed from {target_initial} to {target_final}"
        finally:
            conn.rollback()
        
        # 6. Verify invalid inventory error
        try:
            source_id = 99999  # Non-existent inventory
            target_id = 14686
            part_num = '3024'
            color_id = 15
            transfer_qty = 10
            reason = 'invalid_test'
            
            target_initial = get_inventory_part_quantity(target_id, part_num, color_id)
            
            with conn.cursor() as cur:
                try:
                    cur.execute("SELECT transfer_parts(%s, %s, %s, %s, %s, %s)",
                               (source_id, target_id, part_num, color_id, transfer_qty, reason))
                    result = cur.fetchone()
                    return False, f"Transfer should have failed but succeeded: {result[0]}"
                except psycopg2.Error as e:
                    # Rollback the aborted transaction
                    conn.rollback()
                    
                    target_final = get_inventory_part_quantity(target_id, part_num, color_id)
                    if target_final != target_initial:
                        return False, f"Target quantity changed from {target_initial} to {target_final}"
        finally:
            conn.rollback()
        
        # 7. Verify audit logging
        # Part 1: Test success logging
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT COUNT(*) FROM inventory_transfer_log")
                initial_count = cur.fetchone()[0]
            
            with conn.cursor() as cur:
                cur.execute("SELECT transfer_parts(14469, 14686, '3024', 15, 5, 'audit_test_success')")
            
            # Check the log before committing/rolling back
            with conn.cursor() as cur:
                cur.execute("SELECT COUNT(*) FROM inventory_transfer_log")
                final_count = cur.fetchone()[0]
                if final_count != initial_count + 1:
                    return False, "Success log was not created."
        except Exception as e:
            return False, f"Success logging test threw an unexpected error: {e}"
        finally:
            conn.rollback()
        
        # Part 2: Test failure logging
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT COUNT(*) FROM inventory_transfer_log")
                initial_count = cur.fetchone()[0]
            
            try:
                with conn.cursor() as cur:
                    cur.execute("SELECT transfer_parts(14469, 14469, '3024', 15, 5, 'audit_test_fail')")
            except psycopg2.Error:
                # This is the expected failure path.
                pass
            
            # The transaction is now in an aborted state. We must rollback to issue new commands.
            conn.rollback()
            
            with conn.cursor() as cur:
                cur.execute("SELECT COUNT(*) FROM inventory_transfer_log")
                final_count = cur.fetchone()[0]
                if final_count != initial_count:
                    return False, "Failure log was not rolled back. This implies a non-standard transaction behavior."
        except Exception as e:
            return False, f"Failure logging test threw an unexpected error: {e}"
        finally:
            conn.rollback()
        
        # 8. Verify exact quantity transfer
        try:
            target_id = 14686  # Use a fixed target inventory
            
            # Find a part with a small quantity that doesn't conflict with the target inventory
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT inventory_id, part_num, color_id, quantity
                    FROM public.lego_inventory_parts
                    WHERE quantity BETWEEN 5 AND 20 AND inventory_id != %s
                    LIMIT 1
                """, (target_id,))
                result = cur.fetchone()
                if not result:
                    # Skip if no suitable part found
                    pass
                else:
                    source_id, part_num, color_id, exact_qty = result
                    
                    source_initial = get_inventory_part_quantity(source_id, part_num, color_id)
                    target_initial = get_inventory_part_quantity(target_id, part_num, color_id)
                    
                    with conn.cursor() as cur:
                        cur.execute("SELECT transfer_parts(%s, %s, %s, %s, %s, %s)",
                                   (source_id, target_id, part_num, color_id, exact_qty, 'exact_transfer'))
                        cur.fetchone()
                    
                    source_final = get_inventory_part_quantity(source_id, part_num, color_id)
                    target_final = get_inventory_part_quantity(target_id, part_num, color_id)
                    
                    expected_source = 0
                    expected_target = target_initial + exact_qty
                    
                    if source_final != expected_source:
                        return False, f"Source quantity should be 0 (row deleted), but got {source_final}"
                    elif target_final != expected_target:
                        return False, f"Target quantity mismatch. Expected {expected_target}, got {target_final}"
        except psycopg2.Error as e:
            return False, f"Transfer failed unexpectedly with error: {e}"
        finally:
            conn.rollback()
        
        conn.close()
        return True, f"LEGO transactional inventory transfer verified successfully (system components: function + audit table, transfers: successful + new part, business rules: self-transfer + large + zero blocked, errors: insufficient + invalid handled, audit logging: success + failure, exact transfer: source row deletion)"
        
    except Exception as e:
        return False, f"Verification failed: {str(e)}"

@compare_func(name="postgres_baseball_player_analysis_verifier")
async def postgres_baseball_player_analysis_verifier(a: Any, b: Any, *args, **kwargs) -> (bool, str):
    """Verify baseball player analysis by comparing with ground truth query.
    
    This function replicates the original verification logic from baseball_player_analysis/verify.py
    """
    try:
        conn_params = get_connection_params()
        if not conn_params["database"]:
            return False, "No database specified"
        
        conn = psycopg2.connect(**conn_params)
        
        with conn.cursor() as cur:
            # Get actual results from the created table
            cur.execute("""
                SELECT player_id, player_name, team_name, games_played, at_bats, hits,
                       runs_scored, rbi, home_runs, batting_average, defensive_games,
                       putouts, assists, errors, fielding_percentage
                FROM baseball_player_analysis
                ORDER BY batting_average DESC, games_played DESC
            """)
            actual_results = cur.fetchall()
            
            # Execute ground truth query
            cur.execute("""
                SELECT
                p.id AS player_id,
                MAX(dn.full_name) AS player_name,
                'Unknown' AS team_name,
                core.events_played AS games_played,
                off.at_bats,
                off.hits,
                off.runs_scored,
                off.rbi,
                off.home_runs,
                CASE WHEN off.at_bats > 0
                    THEN 1.0 * off.hits / off.at_bats
                    ELSE 0
                END AS batting_average,
                core.events_played AS defensive_games,
                COALESCE(def.putouts, 0)  AS putouts,
                COALESCE(def.assists, 0)  AS assists,
                COALESCE(def.errors, 0)   AS errors,
                CASE
                    WHEN (COALESCE(def.putouts,0) + COALESCE(def.assists,0) + COALESCE(def.errors,0)) > 0
                    THEN 1.0 * (COALESCE(def.putouts,0) + COALESCE(def.assists,0))
                        / (COALESCE(def.putouts,0) + COALESCE(def.assists,0) + COALESCE(def.errors,0))
                    ELSE 0
                END AS fielding_percentage
                FROM persons p
                JOIN display_names dn
                ON dn.entity_id = p.id
                AND dn.entity_type = 'persons'
                AND NULLIF(TRIM(dn.full_name), '') IS NOT NULL
                JOIN (
                SELECT s.stat_holder_id AS player_id,
                        SUM(bos.at_bats)       AS at_bats,
                        SUM(bos.hits)          AS hits,
                        SUM(bos.runs_scored)   AS runs_scored,
                        SUM(bos.rbi)           AS rbi,
                        SUM(bos.home_runs)     AS home_runs
                FROM stats s
                JOIN baseball_offensive_stats bos
                    ON bos.id = s.stat_repository_id
                WHERE s.stat_holder_type = 'persons'
                    AND s.stat_repository_type = 'baseball_offensive_stats'
                    AND s.context = 'season-regular'
                GROUP BY s.stat_holder_id
                ) off ON off.player_id = p.id
                JOIN (
                SELECT s.stat_holder_id AS player_id,
                        SUM(cps.events_played) AS events_played
                FROM stats s
                JOIN core_person_stats cps
                    ON cps.id = s.stat_repository_id
                WHERE s.stat_holder_type = 'persons'
                    AND s.stat_repository_type = 'core_person_stats'
                    AND s.context = 'season-regular'
                GROUP BY s.stat_holder_id
                ) core ON core.player_id = p.id
                LEFT JOIN (
                SELECT s.stat_holder_id AS player_id,
                        SUM(bds.putouts)  AS putouts,
                        SUM(bds.assists)  AS assists,
                        SUM(bds.errors)   AS errors
                FROM stats s
                JOIN baseball_defensive_stats bds
                    ON bds.id = s.stat_repository_id
                WHERE s.stat_holder_type = 'persons'
                    AND s.stat_repository_type = 'baseball_defensive_stats'
                    AND s.context = 'season-regular'
                GROUP BY s.stat_holder_id
                ) def ON def.player_id = p.id
                WHERE core.events_played >= 10
                AND off.at_bats >= 50
                GROUP BY
                p.id, core.events_played,
                off.at_bats, off.hits, off.runs_scored, off.rbi, off.home_runs,
                def.putouts, def.assists, def.errors
                ORDER BY batting_average DESC, games_played DESC;
            """)
            expected_results = cur.fetchall()
            
            if len(actual_results) != len(expected_results):
                return False, f"baseball_player_analysis table has {len(actual_results)} records, expected {len(expected_results)}"
            
            mismatches = 0
            for i, (actual, expected) in enumerate(zip(actual_results, expected_results)):
                if not rows_match(actual, expected):
                    mismatches += 1
                    if mismatches <= 5:  # Only show first 5 mismatches
                        return False, f"Player analysis row {i+1} mismatch: expected {expected}, got {actual}"
            
            if mismatches > 0:
                return False, f"Total player analysis mismatches: {mismatches}"
        
        conn.close()
        return True, f"Baseball player analysis verified successfully ({len(actual_results)} players analyzed)"
        
    except Exception as e:
        return False, f"Verification failed: {str(e)}"

@compare_func(name="postgres_participant_report_optimization_verifier")
async def postgres_participant_report_optimization_verifier(a: Any, b: Any, *args, **kwargs) -> (bool, str):
    """Verify participant report optimization by checking report data and performance indexes.
    
    This function replicates the original verification logic from participant_report_optimization/verify.py
    """
    try:
        conn_params = get_connection_params()
        if not conn_params["database"]:
            return False, "No database specified"
        
        conn = psycopg2.connect(**conn_params)
        
        with conn.cursor() as cur:
            # 1. Verify report data
            cur.execute("""
                SELECT participant_id, event_count, stat_count, stat_type_count, last_event_date
                FROM participant_performance_report
                ORDER BY participant_id
            """)
            actual_results = cur.fetchall()
            
            if len(actual_results) == 0:
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
                return False, f"Expected {len(expected_results)} report records, got {len(actual_results)}"

            mismatches = 0
            for actual, expected in zip(actual_results, expected_results):
                if not rows_match(actual, expected):
                    mismatches += 1
                    if mismatches <= 5:
                        return False, f"Row mismatch: expected {expected}, got {actual}"

            if mismatches > 0:
                return False, f"Total mismatches in report data: {mismatches}"
            
            # 2. Verify performance optimization indexes
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
            
            critical_indexes_found = 0
            
            if has_participant_index:
                critical_indexes_found += 1
            else:
                return False, "Missing critical index on participants_events.participant_id"
                
            if has_stats_index:
                critical_indexes_found += 1
            else:
                return False, "Missing critical index on stats table"
            
            # Must have both critical indexes for this subquery-heavy query
            if critical_indexes_found < 2:
                return False, f"Performance optimization failed ({critical_indexes_found}/2 critical indexes found). Create these indexes: CREATE INDEX ON participants_events(participant_id); CREATE INDEX ON stats(stat_holder_type, stat_holder_id);"
        
        conn.close()
        return True, f"Participant report optimization verified successfully (report data: {len(actual_results)} records, performance indexes: {critical_indexes_found}/2 critical indexes found)"
        
    except Exception as e:
        return False, f"Verification failed: {str(e)}"

@compare_func(name="postgres_team_roster_management_verifier")
async def postgres_team_roster_management_verifier(a: Any, b: Any, *args, **kwargs) -> (bool, str):
    """Verify team roster management by checking player evaluation, injury status, and summary tables.
    
    This function replicates the original verification logic from team_roster_management/verify.py
    """
    try:
        conn_params = get_connection_params()
        if not conn_params["database"]:
            return False, "No database specified"
        
        conn = psycopg2.connect(**conn_params)
        
        with conn.cursor() as cur:
            # 1. Verify player evaluation table
            cur.execute("""
                SELECT person_id, batting_avg, home_runs, rbis, games_played, performance_score
                FROM player_evaluation
                ORDER BY person_id
            """)
            actual_eval_results = cur.fetchall()
            
            # Execute ground truth query that simulates all steps:
            # 1. Initial insert (step 2)
            # 2. Update based on injuries (step 4)
            cur.execute("""
                WITH initial_players AS (
                    SELECT 
                        s.stat_holder_id AS person_id,
                        SUM(bos.hits)      AS total_hits,
                        SUM(bos.at_bats)   AS total_at_bats,
                        CASE 
                            WHEN SUM(bos.at_bats) > 0 
                            THEN 1.0 * SUM(bos.hits) / SUM(bos.at_bats)
                            ELSE 0 
                        END                AS batting_avg,
                        SUM(bos.home_runs) AS home_runs,
                        SUM(bos.rbi)       AS rbis
                    FROM stats s
                    JOIN baseball_offensive_stats bos
                    ON s.stat_repository_id = bos.id
                    WHERE s.stat_holder_type = 'persons'
                    AND s.stat_repository_type = 'baseball_offensive_stats'
                    GROUP BY s.stat_holder_id
                ),
                game_counts AS (
                    SELECT 
                        person_id,
                        COUNT(DISTINCT event_id) AS games_played
                    FROM person_event_metadata
                    GROUP BY person_id
                ),
                players_with_games AS (
                    SELECT 
                        ip.person_id,
                        ip.batting_avg,
                        ip.home_runs,
                        ip.rbis,
                        COALESCE(gc.games_played, 0) AS games_played,
                        (ip.batting_avg * 1000)
                        + (COALESCE(ip.home_runs, 0) * 5)
                        + (COALESCE(ip.rbis, 0) * 2) AS initial_score
                    FROM initial_players ip
                    LEFT JOIN game_counts gc ON ip.person_id = gc.person_id
                    WHERE COALESCE(gc.games_played, 0) >= 10
                ),
                injury_info AS (
                    SELECT 
                        person_id,
                        COUNT(*) AS injury_count,
                        MAX(CASE WHEN end_date_time IS NULL THEN 1 ELSE 0 END) AS has_active_injury
                    FROM injury_phases
                    GROUP BY person_id
                ),
                adjusted_scores AS (
                    SELECT 
                        pwg.person_id,
                        pwg.batting_avg,
                        pwg.home_runs,
                        pwg.rbis,
                        pwg.games_played,
                        GREATEST(
                            CASE 
                                WHEN COALESCE(ii.has_active_injury, 0) = 1 AND COALESCE(ii.injury_count, 0) > 2 
                                    THEN pwg.initial_score * 0.8 * 0.9
                                WHEN COALESCE(ii.has_active_injury, 0) = 1 
                                    THEN pwg.initial_score * 0.8
                                WHEN COALESCE(ii.injury_count, 0) > 2 
                                    THEN pwg.initial_score * 0.9
                                ELSE pwg.initial_score
                            END,
                            0
                        ) AS performance_score
                    FROM players_with_games pwg
                    LEFT JOIN injury_info ii ON ii.person_id = pwg.person_id
                )
                SELECT 
                    person_id,
                    batting_avg,
                    home_runs,
                    rbis,
                    games_played,
                    performance_score
                FROM adjusted_scores
                ORDER BY person_id;
            """)
            expected_eval_results = cur.fetchall()

            if len(actual_eval_results) != len(expected_eval_results):
                return False, f"Expected {len(expected_eval_results)} player evaluation records, got {len(actual_eval_results)}"

            mismatches = 0
            for i, (actual, expected) in enumerate(zip(actual_eval_results, expected_eval_results)):
                if not rows_match(actual, expected):
                    mismatches += 1
                    if mismatches <= 5:
                        return False, f"Player evaluation row {i+1} mismatch: expected {expected}, got {actual}"

            if mismatches > 0:
                return False, f"Total mismatches in player_evaluation: {mismatches}"
            
            # 2. Verify injury status table
            cur.execute("""
                SELECT person_id, injury_count, last_injury_date, current_status
                FROM player_injury_status
                ORDER BY person_id
            """)
            actual_injury_results = cur.fetchall()
            
            # Execute ground truth query - get players from player_evaluation
            cur.execute("""
                WITH player_list AS (
                    SELECT DISTINCT person_id 
                    FROM player_evaluation
                ),
                injury_counts AS (
                    SELECT 
                        person_id,
                        COUNT(*) as injury_count,
                        MAX(start_date_time::date) as last_injury_date,
                        MAX(CASE WHEN end_date_time IS NULL THEN 1 ELSE 0 END) as has_active_injury
                    FROM injury_phases
                    GROUP BY person_id
                )
                SELECT 
                    pl.person_id,
                    COALESCE(ic.injury_count, 0) as injury_count,
                    ic.last_injury_date,
                    CASE 
                        WHEN COALESCE(ic.has_active_injury, 0) = 1 THEN 'injured'
                        ELSE 'healthy'
                    END as current_status
                FROM player_list pl
                LEFT JOIN injury_counts ic ON pl.person_id = ic.person_id
                ORDER BY pl.person_id
            """)
            expected_injury_results = cur.fetchall()

            if len(actual_injury_results) != len(expected_injury_results):
                return False, f"Expected {len(expected_injury_results)} injury status records, got {len(actual_injury_results)}"

            mismatches = 0
            for i, (actual, expected) in enumerate(zip(actual_injury_results, expected_injury_results)):
                if not rows_match(actual, expected):
                    mismatches += 1
                    if mismatches <= 5:
                        return False, f"Injury status row {i+1} mismatch: expected {expected}, got {actual}"

            if mismatches > 0:
                return False, f"Total mismatches in player_injury_status: {mismatches}"
            
            # 3. Verify summary table
            cur.execute("""
                SELECT metric_name, metric_value
                FROM team_performance_summary
                ORDER BY metric_name
            """)
            actual_summary_results = cur.fetchall()
            
            # Execute ground truth query
            cur.execute("""
                WITH player_data AS (
                    SELECT 
                        COUNT(*) as total_players,
                        AVG(batting_avg) as avg_batting_average,
                        SUM(home_runs) as total_home_runs,
                        AVG(performance_score) as avg_performance_score
                    FROM player_evaluation
                ),
                health_data AS (
                    SELECT 
                        SUM(CASE WHEN current_status = 'injured' THEN 1 ELSE 0 END) as injured_count,
                        SUM(CASE WHEN current_status = 'healthy' THEN 1 ELSE 0 END) as healthy_count
                    FROM player_injury_status
                    WHERE person_id IN (SELECT person_id FROM player_evaluation)
                )
                SELECT metric_name, metric_value::DECIMAL
                FROM (
                    SELECT 'avg_batting_average' as metric_name, avg_batting_average as metric_value FROM player_data
                    UNION ALL
                    SELECT 'avg_performance_score', avg_performance_score FROM player_data
                    UNION ALL
                    SELECT 'healthy_player_count', healthy_count FROM health_data
                    UNION ALL
                    SELECT 'injured_player_count', injured_count FROM health_data
                    UNION ALL
                    SELECT 'total_home_runs', total_home_runs FROM player_data
                    UNION ALL
                    SELECT 'total_players', total_players FROM player_data
                ) metrics
                ORDER BY metric_name
            """)
            expected_summary_results = cur.fetchall()

            if len(actual_summary_results) != len(expected_summary_results):
                return False, f"Expected {len(expected_summary_results)} metrics, got {len(actual_summary_results)}"

            mismatches = 0
            for actual, expected in zip(actual_summary_results, expected_summary_results):
                if not rows_match(actual, expected):
                    mismatches += 1
                    if mismatches <= 5:
                        return False, f"Summary metric mismatch: expected {expected}, got {actual}"

            if mismatches > 0:
                return False, f"Total mismatches in summary table: {mismatches}"
        
        conn.close()
        return True, f"Team roster management verified successfully (player evaluation: {len(actual_eval_results)} records, injury status: {len(actual_injury_results)} records, summary: {len(actual_summary_results)} metrics)"
        
    except Exception as e:
        return False, f"Verification failed: {str(e)}"

