#!/usr/bin/env python3
"""
# pylint: disable=duplicate-code,line-too-long
Verification script for Budget Computation Task
"""

import sys
from pathlib import Path
import os
import json
from collections import Counter

def get_test_directory() -> Path:
    """Get the test directory from FILESYSTEM_TEST_DIR env var."""
    test_root = os.environ.get("FILESYSTEM_TEST_DIR")
    if not test_root:
        raise ValueError("FILESYSTEM_TEST_DIR environment variable is required")

    # Ensure the path includes the category
    # Read category from meta.json
    meta_file = Path(__file__).parent / "meta.json"
    with open(meta_file, 'r', encoding='utf-8') as f:
        meta = json.load(f)
        category = meta.get("category_id", "desktop_template")

    # If test_root doesn't end with category, append it
    test_path = Path(test_root)
    if test_path.name != category:
        test_path = test_path / category

    return test_path

def verify_total_budget_file_exists(test_dir: Path) -> tuple:
    """Verify that the total_budget.txt file exists."""
    budget_file = test_dir / "total_budget.txt"

    if not budget_file.exists():
        print("❌ File 'total_budget.txt' not found")
        return False, "File 'total_budget.txt' not found"

    print("✅ total_budget.txt file found")
    return True, ""

def verify_file_format(test_dir: Path) -> tuple:  # pylint: disable=R0911
    """Verify that the total_budget.txt file has proper format."""
    budget_file = test_dir / "total_budget.txt"

    try:
        content = budget_file.read_text()
        lines = [line.strip() for line in content.split('\n') if line.strip()]

        if len(lines) < 2:
            print("❌ File must contain at least 2 lines (expenses + total)")
            return False, "File must contain at least 2 lines (expenses + total)"

        # Check that all lines except the last follow the format file_path;price
        for i, line in enumerate(lines[:-1]):
            if ';' not in line:
                print(f"❌ Line {i+1} does not contain ';' separator: {line}")
                return False, f"Line {i+1} does not contain ';' separator: {line}"

            parts = line.split(';')
            if len(parts) != 2:
                print(f"❌ Line {i+1} does not have exactly 2 parts: {line}")
                return False, f"Line {i+1} does not have exactly 2 parts: {line}"

            # Check if second part is a valid number
            try:
                float(parts[1])
            except ValueError:
                print(f"❌ Line {i+1} price is not a valid number: {parts[1]}")
                return False, f"Line {i+1} price is not a valid number: {parts[1]}"

        # Check if last line is a valid number (total)
        try:
            float(lines[-1])
        except ValueError:
            print(f"❌ Last line is not a valid number: {lines[-1]}")
            return False, f"Last line is not a valid number: {lines[-1]}"

        print("✅ File format is correct")
        return True, ""

    except (IOError, OSError, UnicodeDecodeError) as e:
        print(f"❌ Error reading file: {e}")
        return False, f"Error reading or parsing file: {e}"

def verify_expense_entries(test_dir: Path) -> tuple:
    """Verify that all 15 required expense entries are present."""
    budget_file = test_dir / "total_budget.txt"

    try:
        content = budget_file.read_text()
        lines = [line.strip() for line in content.split('\n') if line.strip()]

        # Should have 16 lines total (15 expenses + 1 total)
        if len(lines) != 16:
            print(f"❌ Expected 16 lines (15 expenses + 1 total), found {len(lines)}")
            return False, f"Expected 16 lines (15 expenses + 1 total), found {len(lines)}"

        # Check that we have exactly 15 expense entries
        expense_lines = lines[:-1]  # All lines except the last

        if len(expense_lines) != 15:
            print(f"❌ Expected 15 expense entries, found {len(expense_lines)}")
            return False, f"Expected 15 expense entries, found {len(expense_lines)}"

        print("✅ File contains exactly 15 expense entries")
        return True, ""

    except (ValueError, IOError, OSError, AttributeError, KeyError, TypeError, UnicodeDecodeError) as e:
        print(f"❌ Error checking expense entries: {e}")
        return False, f"Error checking expense entries: {e}"

def verify_file_paths_and_counts(test_dir: Path) -> tuple:  # pylint: disable=R0914
    """Verify that all required file paths are present with correct counts."""
    budget_file = test_dir / "total_budget.txt"

    try:
        content = budget_file.read_text()
        lines = [line.strip() for line in content.split('\n') if line.strip()]
        expense_lines = lines[:-1]  # All lines except the last

        # Extract file paths from expense lines
        file_paths = []
        for line in expense_lines:
            file_path = line.split(';')[0]
            file_paths.append(file_path)

        # Count occurrences of each path
        path_counts = Counter(file_paths)

        # Expected file paths and their counts based on answer.txt
        expected_paths = {
            'Archives/tax_documents_2022.csv': 3,
            'Documents/Personal/tax_info_2023.csv': 3,
            'Documents/budget.csv': 3,
            'Downloads/expenses.csv': 3,
            'Downloads/price_comparisons.csv': 3
        }

        # Helper function to check if a path contains the expected path
        def path_matches_expected(actual_path: str, expected_path: str) -> bool:
            """Check if actual path contains the expected path
            (allowing for prefixes like './')
            """
            # Remove common prefixes like './', '../', etc.
            normalized_actual = actual_path
            while (normalized_actual.startswith('./') or
                   normalized_actual.startswith('../')):
                if normalized_actual.startswith('./'):
                    normalized_actual = normalized_actual[2:]
                else:
                    normalized_actual = normalized_actual[3:]

            # Check if the normalized path contains the expected path
            return expected_path in normalized_actual or normalized_actual == expected_path

        # Check if all expected paths are present with correct counts
        for expected_path, expected_count in expected_paths.items():
            # Find matching actual paths
            matching_paths = []
            for actual_path in path_counts.keys():
                if path_matches_expected(actual_path, expected_path):
                    matching_paths.append(actual_path)

            if not matching_paths:
                print(f"❌ Missing expected file path: {expected_path}")
                return False, f"Missing expected file path: {expected_path}"

            # Sum up the counts from all matching paths
            total_count = sum(path_counts[path] for path in matching_paths)
            if total_count != expected_count:
                msg = (f"Path {expected_path} has wrong count: "
                       f"expected {expected_count}, found {total_count}")
                print(f"❌ {msg}")
                print(f"   Matching paths: {matching_paths}")
                return False, msg

        # Check if there are any completely unexpected paths
        # (not matching any expected path)
        all_matching_paths = set()
        for expected_path in expected_paths:
            for actual_path in path_counts:
                if path_matches_expected(actual_path, expected_path):
                    all_matching_paths.add(actual_path)

        unexpected_paths = set(path_counts) - all_matching_paths
        if unexpected_paths:
            print(f"❌ Unexpected file paths found: {unexpected_paths}")
            return False, f"Unexpected file paths found: {unexpected_paths}"

        print("✅ All expected file paths are present with correct counts")
        return True, ""

    except (IOError, OSError, UnicodeDecodeError) as e:
        print(f"❌ Error checking file: {e}")
        return False, f"Error checking file paths: {e}"

def verify_individual_prices(test_dir: Path) -> tuple:  # pylint: disable=R0914
    """Verify that all individual prices match the expected values."""
    budget_file = test_dir / "total_budget.txt"

    try:
        content = budget_file.read_text()
        lines = [line.strip() for line in content.split('\n') if line.strip()]
        expense_lines = lines[:-1]  # All lines except the last

        # Expected prices based on answer.txt
        expected_expenses = [
            ('Archives/tax_documents_2022.csv', 42000.00),
            ('Archives/tax_documents_2022.csv', 1800.00),
            ('Archives/tax_documents_2022.csv', 950.00),
            ('Documents/Personal/tax_info_2023.csv', 45000.00),
            ('Documents/Personal/tax_info_2023.csv', 2500.00),
            ('Documents/Personal/tax_info_2023.csv', 1200.00),
            ('Documents/budget.csv', 250.00),
            ('Documents/budget.csv', 180.00),
            ('Documents/budget.csv', 120.00),
            ('Downloads/expenses.csv', 45.99),
            ('Downloads/expenses.csv', 99.00),
            ('Downloads/expenses.csv', 234.50),
            ('Downloads/price_comparisons.csv', 879.99),
            ('Downloads/price_comparisons.csv', 289.99),
            ('Downloads/price_comparisons.csv', 74.99)
        ]

        # Helper function to check if a path contains the expected path
        def path_matches_expected(actual_path: str, expected_path: str) -> bool:
            """Check if actual path contains the expected path
            (allowing for prefixes like './')
            """
            # Remove common prefixes like './', '../', etc.
            normalized_actual = actual_path
            while (normalized_actual.startswith('./') or
                   normalized_actual.startswith('../')):
                if normalized_actual.startswith('./'):
                    normalized_actual = normalized_actual[2:]
                else:
                    normalized_actual = normalized_actual[3:]

            # Check if the normalized path contains the expected path
            return expected_path in normalized_actual or normalized_actual == expected_path

        # Parse actual expenses
        actual_expenses = []
        for line in expense_lines:
            parts = line.split(';')
            file_path = parts[0]
            price = float(parts[1])
            actual_expenses.append((file_path, price))

        # Create a counter for expected expenses to handle duplicates
        expected_expenses_counter = Counter(expected_expenses)
        actual_expenses_counter = Counter(actual_expenses)

        # Check if all expected expenses are present with correct counts
        for expected_expense, expected_count in expected_expenses_counter.items():
            expected_path, expected_price = expected_expense

            # Find matching actual expenses
            matching_expenses = []
            for actual_expense in actual_expenses_counter:
                actual_path, actual_price = actual_expense
                price_match = abs(actual_price - expected_price) < 0.01
                path_match = path_matches_expected(actual_path, expected_path)
                if path_match and price_match:
                    matching_expenses.append(actual_expense)

            if not matching_expenses:
                msg = f"Missing expected expense: {expected_expense}"
                print(f"❌ {msg}")
                return False, msg

            # Sum up the counts from all matching expenses
            total_count = sum(actual_expenses_counter[expense]
                             for expense in matching_expenses)
            if total_count != expected_count:
                msg = (f"Expense {expected_expense} has wrong count: "
                       f"expected {expected_count}, found {total_count}")
                print(f"❌ {msg}")
                print(f"   Matching expenses: {matching_expenses}")
                return False, msg

        # Check if there are any completely unexpected expenses
        # (not matching any expected expense)
        all_matching_expenses = set()
        for expected_expense in expected_expenses_counter.keys():
            expected_path, expected_price = expected_expense
            for actual_expense in actual_expenses_counter.keys():
                actual_path, actual_price = actual_expense
                if (path_matches_expected(actual_path, expected_path) and
                    abs(actual_price - expected_price) < 0.01):
                    all_matching_expenses.add(actual_expense)

        unexpected_expenses = set(actual_expenses_counter.keys()) - all_matching_expenses
        if unexpected_expenses:
            print(f"❌ Unexpected expenses found: {unexpected_expenses}")
            return False, f"Unexpected expenses found: {unexpected_expenses}"

        print("✅ All individual prices match expected values")
        return True, ""

    except (ValueError, IOError, OSError, AttributeError, KeyError, TypeError, UnicodeDecodeError) as e:
        print(f"❌ Error checking individual prices: {e}")
        return False, f"Error checking individual prices: {e}"

def verify_total_price(test_dir: Path) -> tuple:
    """Verify that the total price is correct."""
    budget_file = test_dir / "total_budget.txt"

    try:
        content = budget_file.read_text()
        lines = [line.strip() for line in content.split('\n') if line.strip()]

        # Get the total from the last line
        total_line = lines[-1]
        try:
            actual_total = float(total_line)
        except ValueError:
            print(f"❌ Last line is not a valid number: {total_line}")
            return False, f"Last line is not a valid number: {total_line}"

        # Expected total based on answer.txt
        expected_total = 95624.46

        if abs(actual_total - expected_total) > 0.01:  # Allow small floating point differences
            print(f"❌ Expected total {expected_total}, found {actual_total}")
            return False, f"Expected total {expected_total}, found {actual_total}"

        print("✅ Total price is correct")
        return True, ""

    except (ValueError, IOError, OSError, AttributeError, KeyError, TypeError, UnicodeDecodeError) as e:
        print(f"❌ Error checking total price: {e}")
        return False, f"Error checking total price: {e}"

def verify_total_calculation(test_dir: Path) -> tuple:
    """Verify that the total matches the sum of individual expenses."""
    budget_file = test_dir / "total_budget.txt"

    try:
        content = budget_file.read_text()
        lines = [line.strip() for line in content.split('\n') if line.strip()]
        expense_lines = lines[:-1]  # All lines except the last

        # Calculate sum of individual expenses
        calculated_total = 0.0
        for line in expense_lines:
            price = float(line.split(';')[1])
            calculated_total += price

        # Get the stated total from the last line
        stated_total = float(lines[-1])

        # Check if they match (allow small floating point differences)
        if abs(calculated_total - stated_total) > 0.01:
            msg = (f"Total calculation mismatch: "
                   f"calculated {calculated_total:.2f}, "
                   f"stated {stated_total:.2f}")
            print(f"❌ {msg}")
            return False, msg

        print("✅ Total calculation is correct")
        return True, ""

    except (ValueError, IOError, OSError, AttributeError, KeyError, TypeError, UnicodeDecodeError) as e:
        print(f"❌ Error verifying total calculation: {e}")
        return False, f"Error verifying total calculation: {e}"

def verify(test_dir: Path) -> tuple:
    """Verify function with same logic as main, returning (bool, str) tuple."""
    print("🔍 Verifying Budget Computation Task...")

    # Define verification steps
    verification_steps = [
        ("Total Budget File Exists", verify_total_budget_file_exists),
        ("File Format", verify_file_format),
        ("Expense Entries Count", verify_expense_entries),
        ("File Paths and Counts", verify_file_paths_and_counts),
        ("Individual Prices", verify_individual_prices),
        ("Total Price", verify_total_price),
        ("Total Calculation", verify_total_calculation),
    ]

    # Run all verification steps
    for step_name, verify_func in verification_steps:
        print(f"\n--- {step_name} ---")
        passed, error_msg = verify_func(test_dir)
        if not passed:
            return False, error_msg

    # Final result
    print("\n" + "="*50)
    print("✅ Budget computation task completed successfully!")
    print("🎉 All verification steps passed")
    print("📊 Summary:")
    print("   - 15 expense entries found")
    print("   - 5 different file paths covered")
    print("   - All individual prices correct")
    print("   - Total price: $95,624.46")
    print("   - Calculation verified")
    return True, ""

def main():
    """Main verification function."""
    test_dir = get_test_directory()
    passed, error_msg = verify(test_dir)

    if passed:
        sys.exit(0)
    else:
        print(f"\n❌ Budget computation task verification: FAIL - {error_msg}")
        print("Please check the errors above and ensure all requirements are met")
        sys.exit(1)

if __name__ == "__main__":
    main()
