"""
Verification script for PostgreSQL Task 2: Customer Data Migration
"""
# pylint: disable=duplicate-code

import os
import pickle
import sys

import psycopg2  # type: ignore

def get_connection_params() -> dict:
    """Get database connection parameters."""
    return {
        "host": os.getenv("POSTGRES_HOST", "localhost"),
        "port": int(os.getenv("POSTGRES_PORT", "5432")),
        "database": os.getenv("POSTGRES_DATABASE"),
        "user": os.getenv("POSTGRES_USERNAME"),
        "password": os.getenv("POSTGRES_PASSWORD")
    }

def load_expected_customers():
    """Load the expected customer data from pickle file."""
    script_dir = os.path.dirname(os.path.abspath(__file__))
    pkl_path = os.path.join(script_dir, 'customer_data.pkl')

    try:
        with open(pkl_path, 'rb') as f:
            return pickle.load(f)
    except FileNotFoundError:
        print(f"❌ customer_data.pkl not found at {pkl_path}. Please generate customer data first.")
        return None
    except (psycopg2.Error, ValueError, KeyError, TypeError) as e:
        print(f"❌ Error loading customer data: {e}")
        return None

def verify_migrated_customers(conn, expected_customers) -> tuple[bool, str]:
    """Verify migrated customers by comparing with expected data as sets."""
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
            print(
                f"❌ Expected {len(expected_customers)} migrated customers, "
                f"found {len(actual_customers)}"
            )
            return False, (
                f"Expected {len(expected_customers)} migrated customers, "
                f"found {len(actual_customers)}"
            )

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
            # Convert all fields to strings for consistent comparison
            actual_tuple = (
                str(row[0]) if row[0] is not None else '',  # FirstName
                str(row[1]) if row[1] is not None else '',  # LastName
                str(row[2]) if row[2] is not None else '',  # Company
                str(row[3]) if row[3] is not None else '',  # Address
                str(row[4]) if row[4] is not None else '',  # City
                str(row[5]) if row[5] is not None else '',  # State
                str(row[6]) if row[6] is not None else '',  # Country
                str(row[7]) if row[7] is not None else '',  # PostalCode
                str(row[8]) if row[8] is not None else '',  # Phone
                str(row[9]) if row[9] is not None else '',  # Email
                int(row[10]) if row[10] is not None else None,  # SupportRepId
                row[11]  # Fax (should be None)
            )
            actual_tuples.add(actual_tuple)

        # Check if sets are equal
        if actual_tuples != expected_tuples:
            missing_in_actual = expected_tuples - actual_tuples
            extra_in_actual = actual_tuples - expected_tuples

            print("❌ Customer data sets don't match!")
            if missing_in_actual:
                print(f"   Missing {len(missing_in_actual)} expected customers")
                for missing in list(missing_in_actual)[:3]:  # Show first 3
                    print(f"   Missing: {missing[0]} {missing[1]} - {missing[2]}")
                if len(missing_in_actual) > 3:
                    print(f"   ... and {len(missing_in_actual) - 3} more")

            if extra_in_actual:
                print(f"   Found {len(extra_in_actual)} unexpected customers")
                for extra in list(extra_in_actual)[:3]:  # Show first 3
                    print(f"   Extra: {extra[0]} {extra[1]} - {extra[2]}")
                if len(extra_in_actual) > 3:
                    print(f"   ... and {len(extra_in_actual) - 3} more")

            return False, "Customer data sets don't match!"

        print(f"✅ All {len(expected_customers)} customers migrated correctly")
        print("✅ All customers assigned to SupportRepId 3")
        print("✅ All customers have Fax field set to NULL")
        print("✅ Customer data sets match exactly (order-independent)")

        return True, ""

def verify() -> tuple[bool, str]:
    """Verification function for customer data migration task."""
    print("=" * 60)
    print("Verifying Customer Data Migration Task")
    print("=" * 60)

    # Load expected customer data
    expected_customers = load_expected_customers()
    if not expected_customers:
        return False, "Failed to load expected customer data"

    print(f"Loaded {len(expected_customers)} expected customer records")

    # Get connection parameters
    conn_params = get_connection_params()

    if not conn_params["database"]:
        print("❌ No database specified")
        return False, "No database specified"

    try:
        # Connect to database
        conn = psycopg2.connect(**conn_params)

        # Verify migration
        success, error_msg = verify_migrated_customers(conn, expected_customers)

        conn.close()

        if success:
            print("\n🎉 Task verification: PASS")
            return True, ""
        print("\n❌ Task verification: FAIL")
        return False, error_msg

    except psycopg2.Error as e:
        print(f"❌ Database error: {e}")
        return False, f"Database error: {e}"
    except (psycopg2.Error, ValueError, KeyError, TypeError) as e:
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
