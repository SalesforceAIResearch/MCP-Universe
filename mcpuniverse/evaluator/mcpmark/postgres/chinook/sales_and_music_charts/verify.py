"""
Verification script for PostgreSQL Task 1: Monthly Sales Dashboard and Music Charts
"""
# pylint: disable=too-many-return-statements,duplicate-code

import os
import sys
from decimal import Decimal

import psycopg2

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

def verify_monthly_sales_results(conn) -> tuple[bool, str]:
    """Verify the monthly sales summary results."""
    with conn.cursor() as cur:
        # Get actual results from the created table
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
            print(
                f"❌ Expected {len(expected_results)} monthly sales "
                f"records, got {len(actual_results)}"
            )
            return False, (
                f"Expected {len(expected_results)} monthly sales "
                f"records, got {len(actual_results)}"
            )

        mismatches = 0
        for i, (actual, expected) in enumerate(zip(actual_results, expected_results)):
            if not rows_match(actual, expected):
                if mismatches < 5:  # Only show first 5 mismatches
                    print(f"❌ Monthly sales row {i+1} mismatch: expected {expected}, got {actual}")
                mismatches += 1

        if mismatches > 0:
            print(f"❌ Total monthly sales mismatches: {mismatches}")
            return False, f"Total monthly sales mismatches: {mismatches}"

        print(f"✅ Monthly sales results are correct ({len(actual_results)} records)")
        return True, ""

def verify_music_charts_results(conn) -> tuple[bool, str]:
    """Verify the music charts results."""
    with conn.cursor() as cur:
        # Get actual results from the created table
        cur.execute("""
            SELECT chart_type, rank_position, item_id, item_name, total_revenue
            FROM top_music_charts
            ORDER BY chart_type, rank_position
        """)
        actual_results = cur.fetchall()

        # Execute ground truth queries for each chart type
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
        expected_results = cur.fetchall()

        if len(actual_results) != len(expected_results):
            print(
                f"❌ Expected {len(expected_results)} music chart "
                f"records, got {len(actual_results)}"
            )
            return False, (
                f"Expected {len(expected_results)} music chart "
                f"records, got {len(actual_results)}"
            )

        mismatches = 0
        for i, (actual, expected) in enumerate(zip(actual_results, expected_results)):
            if not rows_match(actual, expected):
                if mismatches < 5:  # Only show first 5 mismatches
                    print(f"❌ Music chart row {i+1} mismatch: expected {expected}, got {actual}")
                mismatches += 1

        if mismatches > 0:
            print(f"❌ Total music chart mismatches: {mismatches}")
            return False, f"Total music chart mismatches: {mismatches}"

        print(f"✅ Music chart results are correct ({len(actual_results)} records)")
        return True, ""

def verify() -> tuple[bool, str]:
    """Verification function for sales and music charts task."""
    print("=" * 50)

    # Get connection parameters
    conn_params = get_connection_params()

    if not conn_params["database"]:
        print("❌ No database specified")
        return False, "No database specified"

    try:
        # Connect to database
        conn = psycopg2.connect(**conn_params)

        # Verify monthly sales results
        success, error_msg = verify_monthly_sales_results(conn)
        if not success:
            conn.close()
            return False, error_msg

        # Verify music charts results
        success, error_msg = verify_music_charts_results(conn)
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
