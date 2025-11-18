"""
Verification script for PostgreSQL Sports Task 1: Baseball Player Analysis
"""
# pylint: disable=too-many-return-statements,duplicate-code

import os
import sys
from decimal import Decimal

import psycopg2

def rows_match(actual_row, expected_row):
    """Compare two rows with appropriate tolerance for decimals and floats."""
    if len(actual_row) != len(expected_row):
        return False

    for actual, expected in zip(actual_row, expected_row):
        if isinstance(actual, (Decimal, float)) and isinstance(expected, (Decimal, float)):
            # Use higher tolerance for floating point comparisons
            if abs(float(actual) - float(expected)) > 0.001:
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

def verify_baseball_player_analysis_table(conn) -> tuple[bool, str]:
    """Verify the baseball_player_analysis table results."""
    with conn.cursor() as cur:
        cur.execute("""
            SELECT player_id, player_name, team_name, games_played, at_bats, hits,
                   runs_scored, rbi, home_runs, batting_average, defensive_games,
                   putouts, assists, errors, fielding_percentage
            FROM baseball_player_analysis
            ORDER BY batting_average DESC, games_played DESC
        """)
        actual_results = cur.fetchall()

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
            print(
                f"❌ baseball_player_analysis table has "
                f"{len(actual_results)} records, expected "
                f"{len(expected_results)}"
            )
            return False, (
                f"baseball_player_analysis table has "
                f"{len(actual_results)} records, expected "
                f"{len(expected_results)}"
            )

        mismatches = 0
        for i, (actual, expected) in enumerate(zip(actual_results, expected_results)):
            if not rows_match(actual, expected):
                if mismatches < 5:  # Only show first 5 mismatches
                    print(
                        f"❌ Player analysis row {i+1} mismatch: "
                        f"expected {expected}, got {actual}"
                    )
                mismatches += 1

        if mismatches > 0:
            print(f"❌ Total player analysis mismatches: {mismatches}")
            return False, f"Total player analysis mismatches: {mismatches}"

        print(
            f"✅ baseball_player_analysis table created and populated "
            f"correctly ({len(actual_results)} players)"
        )
        return True, ""

def verify() -> tuple[bool, str]:
    """Verification function for baseball player analysis task."""
    print("=" * 70)
    print("PostgreSQL Sports Task 1 Verification: Baseball Player Analysis")
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
        success, error_msg = verify_baseball_player_analysis_table(conn)

        conn.close()

        if success:
            print("\n🎉 Task verification: PASS")
            return True, ""
        print("\n❌ Task verification: FAIL")
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
