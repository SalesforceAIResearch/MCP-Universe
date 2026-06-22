Please use FileSystem tools to finish the following task:

Read all the files under current path, extract every time/plan information that clearly indicates 2024, and integrate them into a list and create a file in main directory called `timeline.txt`. Write the timeline in the file in the following format.

### Rules
- If a task only shows month without day, use the 1st day of that month
- If a task only shows year without month and day, skip it.
- If a file shows multiple tasks on the same date, count only once per date

### Output Format
- Each line format: `file_path:time`
    - `file_path`: The file path where this time information appears (**relative to the current path**)
    - `time`: Specific time, if it's a time period, write the start time (YYYY-MM-DD)

### Sorting Requirements
- Sort by chronological order
