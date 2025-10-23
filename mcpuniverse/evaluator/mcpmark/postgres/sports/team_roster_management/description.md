# Team Roster Management Operations

## Background
You need to manage team rosters for the upcoming season, including player transfers, injury tracking, and performance evaluations.

## Requirements

Complete the following 5 operations in order:

### 1. Set Up Player Performance Tracking
Create a table called `player_evaluation` with the following structure:
- performance_id (serial primary key)
- person_id (integer not null, references persons(id))
- batting_avg (decimal)
- home_runs (integer)
- rbis (integer)
- games_played (integer)
- performance_score (decimal)
- evaluation_date (date)

Add constraint: CHECK (batting_avg BETWEEN 0 AND 1)

### 2. Load Historical Player Statistics
Insert player performance data into `player_evaluation`:
- Select all players who have offensive statistics
- Calculate batting_avg as hits/at_bats (handle division by zero)
- Sum up home_runs, rbi from baseball_offensive_stats
- Count games_played from person_event_metadata
- Calculate performance_score as: (batting_avg * 1000) + (home_runs * 5) + (rbi * 2)
- Only include players with at least 10 games played
- Set evaluation_date to '2024-01-01'

### 3. Track Player Health Status
Create a table called `player_injury_status`:
- status_id (serial primary key)
- person_id (integer unique not null)
- injury_count (integer default 0)
- last_injury_date (date)
- current_status (varchar check in ('healthy', 'injured', 'recovering'))

Insert data by:
- Including all players from player_evaluation
- Count injuries from injury_phases for each player
- Get the most recent injury start_date as last_injury_date
- Set current_status: 'injured' if injury has no end_date, otherwise 'healthy'

### 4. Adjust Scores Based on Health
Update `player_evaluation` to reduce performance scores for injured players:
- Reduce performance_score by 20% for players with current_status = 'injured'
- Reduce performance_score by 10% for players with injury_count > 2
- Set minimum performance_score to 0 (no negative scores)

### 5. Generate Performance Summary Report
Create a summary table called `team_performance_summary`:
- summary_id (serial primary key)
- metric_name (varchar unique)
- metric_value (decimal)

Insert the following metrics:
- 'total_players' - count of players in player_evaluation
- 'avg_batting_average' - average batting_avg
- 'total_home_runs' - sum of all home_runs
- 'avg_performance_score' - average performance_score
- 'injured_player_count' - count of injured players
- 'healthy_player_count' - count of healthy players

## Important Notes
- Handle NULL values appropriately (treat as 0 where needed)
- Ensure foreign key constraints are properly set
- Do NOT use ROUND functions in calculations
- Use COALESCE to handle NULL values in calculations