"""
Verification script for PostgreSQL Sports Task 2: Team Roster Management Operations
"""
# pylint: disable=too-many-return-statements,duplicate-code

import os
import sys
from decimal import Decimal

import psycopg2

def rows_match(actual_row, expected_row):
    """
    Compare two rows with appropriate tolerance.
    For Decimal types: allows 0.001 tolerance
    For other types: requires exact match
    """
    if len(actual_row) != len(expected_row):
        return False

    for actual, expected in zip(actual_row, expected_row):
        if isinstance(actual, Decimal) and isinstance(expected, Decimal):
            if abs(float(actual) - float(expected)) > 0.001:
                return False
        elif isinstance(actual, float) and isinstance(expected, float):
            if abs(actual - expected) > 0.001:
                return False
        elif actual != expected:
            return False

    return True

def get_connection_params() -> dict:
    """Get database connection parameters."""
    return {
        "host": os.getenv("POSTGRES_HOST", "localhost"),
        "port": int(os.getenv("POSTGRES_PORT", "5432")),
        "database": os.getenv("POSTGRES_DATABASE", "sports"),
        "user": os.getenv("POSTGRES_USERNAME", "postgres"),
        "password": os.getenv("POSTGRES_PASSWORD", "postgres")
    }

def verify_player_evaluation_table(conn) -> tuple[bool, str]:
    """Verify the final state of player_evaluation table after all operations."""
    with conn.cursor() as cur:
        # Get actual results from the created table
        cur.execute("""
            SELECT person_id, batting_avg, home_runs, rbis, games_played, performance_score
            FROM player_evaluation
            ORDER BY person_id
        """)
        actual_results = cur.fetchall()

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
        expected_results = cur.fetchall()

        if len(actual_results) != len(expected_results):
            print(
                f"❌ Expected {len(expected_results)} player evaluation "
                f"records, got {len(actual_results)}"
            )
            return False, (
                f"Expected {len(expected_results)} player evaluation "
                f"records, got {len(actual_results)}"
            )

        mismatches = 0
        for i, (actual, expected) in enumerate(zip(actual_results, expected_results)):
            if not rows_match(actual, expected):
                if mismatches < 5:  # Only show first 5 mismatches
                    print(f"❌ Row {i+1} mismatch: expected {expected}, got {actual}")
                mismatches += 1

        if mismatches > 0:
            print(f"❌ Total mismatches in player_evaluation: {mismatches}")
            return False, f"Total mismatches in player_evaluation: {mismatches}"

        print(f"✅ Player evaluation table is correct ({len(actual_results)} records)")
        return True, ""

def verify_injury_status_table(conn) -> tuple[bool, str]:
    """Verify the player_injury_status table and data."""
    with conn.cursor() as cur:
        # Get actual results
        cur.execute("""
            SELECT person_id, injury_count, last_injury_date, current_status
            FROM player_injury_status
            ORDER BY person_id
        """)
        actual_results = cur.fetchall()

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
        expected_results = cur.fetchall()

        if len(actual_results) != len(expected_results):
            print(
                f"❌ Expected {len(expected_results)} injury status "
                f"records, got {len(actual_results)}"
            )
            return False, (
                f"Expected {len(expected_results)} injury status "
                f"records, got {len(actual_results)}"
            )

        mismatches = 0
        for i, (actual, expected) in enumerate(zip(actual_results, expected_results)):
            if not rows_match(actual, expected):
                if mismatches < 5:
                    print(f"❌ Row {i+1} mismatch: expected {expected}, got {actual}")
                mismatches += 1

        if mismatches > 0:
            print(f"❌ Total mismatches in player_injury_status: {mismatches}")
            return False, f"Total mismatches in player_injury_status: {mismatches}"

        print(f"✅ Player injury status table is correct ({len(actual_results)} records)")
        return True, ""


def verify_summary_table(conn) -> tuple[bool, str]:
    """Verify the team_performance_summary table."""
    with conn.cursor() as cur:
        # Get actual results
        cur.execute("""
            SELECT metric_name, metric_value
            FROM team_performance_summary
            ORDER BY metric_name
        """)
        actual_results = cur.fetchall()

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
        expected_results = cur.fetchall()

        if len(actual_results) != len(expected_results):
            print(f"❌ Expected {len(expected_results)} metrics, got {len(actual_results)}")
            return False, f"Expected {len(expected_results)} metrics, got {len(actual_results)}"

        mismatches = 0
        for actual, expected in zip(actual_results, expected_results):
            if not rows_match(actual, expected):
                if mismatches < 5:
                    print(f"❌ Metric mismatch: expected {expected}, got {actual}")
                mismatches += 1

        if mismatches > 0:
            print(f"❌ Total mismatches in summary table: {mismatches}")
            return False, f"Total mismatches in summary table: {mismatches}"

        print(f"✅ Team performance summary table is correct ({len(actual_results)} metrics)")
        return True, ""

def verify() -> tuple[bool, str]:
    """Verification function for team roster management task."""
    print("=" * 50)
    print("Verifying Sports Task 2: Team Roster Management Operations")
    print("=" * 50)

    # Get connection parameters
    conn_params = get_connection_params()

    if not conn_params["database"]:
        print("❌ No database specified")
        return False, "No database specified"

    try:
        # Connect to database
        conn = psycopg2.connect(**conn_params)

        # Verify all steps
        success, error_msg = verify_player_evaluation_table(conn)
        if not success:
            conn.close()
            return False, error_msg

        success, error_msg = verify_injury_status_table(conn)
        if not success:
            conn.close()
            return False, error_msg

        success, error_msg = verify_summary_table(conn)
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
