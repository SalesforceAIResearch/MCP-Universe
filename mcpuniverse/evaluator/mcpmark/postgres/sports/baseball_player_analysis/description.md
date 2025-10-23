Create comprehensive baseball player performance analysis in the sports database.

## Background

You are a sports analyst working with a comprehensive sports database. The analytics team needs to create a detailed analysis of baseball players by combining their offensive and defensive statistics with personal information. Currently, this data is scattered across multiple tables and needs to be consolidated for reporting purposes.

## Your Task

Create a table called `baseball_player_analysis` that consolidates baseball player performance data. The table should provide a comprehensive view of each qualifying player's performance metrics.

### Table Structure

Create the `baseball_player_analysis` table with the following columns:
- `player_id` (INTEGER, NOT NULL) - Player identifier
- `player_name` (VARCHAR(255), NOT NULL) - Player's full name
- `team_name` (VARCHAR(255)) - Set to 'Unknown' for all players
- `games_played` (INTEGER) - Number of games/events the player participated in
- `at_bats` (INTEGER) - Total at-bats for the player
- `hits` (INTEGER) - Total hits for the player
- `runs_scored` (INTEGER) - Total runs scored by the player
- `rbi` (INTEGER) - Total runs batted in by the player
- `home_runs` (INTEGER) - Total home runs hit by the player
- `batting_average` (DECIMAL) - Calculated as hits/at_bats
- `defensive_games` (INTEGER) - Number of defensive games played (same as games_played)
- `putouts` (INTEGER) - Total putouts in defensive play
- `assists` (INTEGER) - Total assists in defensive play
- `errors` (INTEGER) - Total errors made in defensive play
- `fielding_percentage` (DECIMAL) - Calculated as (putouts + assists)/(putouts + assists + errors)

### Data Requirements

Include only baseball players that meet ALL of the following criteria:
- Have offensive statistics available for regular season play
- Have played at least 10 games/events
- Have at least 50 at-bats
- Have a valid name available in the system

### Important Notes

- Focus on regular season statistics only
- Handle NULL values appropriately in calculations (use 0 for missing stats)
- Ensure batting average and fielding percentage calculations handle division by zero
- Do NOT use ROUND functions - keep the full precision of calculated values
- Sort results by batting average descending, then by games played descending

## Requirements

- Explore the database to understand the table structure and relationships
- Create the table with the exact structure specified above
- Populate the table using appropriate queries and joins
- Ensure all calculations are mathematically correct
- Handle edge cases properly (division by zero, NULL values)