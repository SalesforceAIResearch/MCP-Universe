Please use FileSystem tools to finish the following task:

### 1. Data Loading

- Read and extract song information from `jay_chou/`
- Read and extract song information from `jj_lin/`

### 2. Popularity Score Calculation

For each songs, calculate popularity scores using this formula (keep 3 decimal places):

```
popularity_score = (rating × 0.4) + (play_count_normalized × 0.4) + (year_factor × 0.2)

Where:
- rating: song rating (1-5 scale)
- play_count_normalized: play_count / 250 (0-1 scale)
- year_factor: (2025 - release_year) / 25 (recency bonus)
```

### 3. Generate Analysis Report

Create a file named `music_analysis_report.txt`

 in the `music/` folder with the following exact format:

**Lines 1-20**: Each line contains one song in format `songname:popularity_score`

- Sort songs by popularity_score in descending order (highest first)
- Use exact song names as they appear in the source files
- Include all 20 songs from both artists

**Lines 21-25**: Top 5 song names only (one per line)

- List the top 5 songs by popularity_score
- No scores, just song names
- One song name per line

**Important**: The file must contain exactly 25 lines with no additional content, headers, or formatting.
