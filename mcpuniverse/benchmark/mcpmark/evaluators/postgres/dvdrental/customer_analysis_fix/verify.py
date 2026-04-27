"""
Verification script for PostgreSQL Task 3: Fix Customer Analysis Query
"""
# pylint: disable=too-many-return-statements,duplicate-code

import os
import sys
from decimal import Decimal

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

def rows_match(actual_row, expected_row):
    """Compare two rows with appropriate tolerance for decimals and floats."""
    if len(actual_row) != len(expected_row):
        return False

    for actual, expected in zip(actual_row, expected_row):
        if isinstance(actual, (Decimal, float)) and isinstance(expected, (Decimal, float)):
            # Use higher tolerance for floating point comparisons
            if abs(float(actual) - float(expected)) > 0.1:
                return False
        elif actual != expected:
            return False

    return True

def verify_customer_analysis_fixed_table(conn) -> tuple[bool, str]:
    """Verify the customer_analysis_fixed table results."""
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
            print(f"❌ Expected {len(expected_results)} rows, got {len(actual_results)}")
            return False, f"Expected {len(expected_results)} rows, got {len(actual_results)}"

        mismatches = 0
        for i, (actual, expected) in enumerate(zip(actual_results, expected_results)):
            if not rows_match(actual, expected):
                if mismatches < 5:  # Only show first 5 mismatches
                    print(f"❌ Row {i+1} mismatch:")
                    print(f"   Expected: {expected}")
                    print(f"   Actual:   {actual}")
                mismatches += 1

        if mismatches > 0:
            print(f"❌ Total mismatches: {mismatches}")
            return False, f"Total mismatches: {mismatches}"

        print(f"✅ Query results are correct ({len(actual_results)} rows)")
        return True, ""

def verify() -> tuple[bool, str]:
    """Verification function for customer analysis fix task."""
    print("=" * 70)
    print("PostgreSQL Task 3 Verification: Fix Customer Analysis Query")
    print("=" * 70)

    # Get connection parameters
    conn_params = get_connection_params()

    if not conn_params["database"]:
        print("❌ No database specified")
        return False, "No database specified"

    try:
        # Connect to database
        conn = psycopg2.connect(**conn_params)

        # Verify results
        success, error_msg = verify_customer_analysis_fixed_table(conn)

        conn.close()

        if success:
            print("\n🎉 Task verification: PASS")
            print("   - Query was successfully debugged and fixed")
            print("   - All 587 rows match the expected results")
            return True, ""
        print("\n❌ Task verification: FAIL")
        print("   - The query still has issues")
        print("   - Please review the duplicate counting problem")
        return False, error_msg

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
