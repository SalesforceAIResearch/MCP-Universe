Please use FileSystem tools to finish the following task:

### Task Description

Analyze the creation time (ctime) of all files in the test directory and organize them into a hierarchical directory structure based on their creation dates.

### Task Objectives

1. **Read metadata** of all files in the test directory
2. **Analyze creation times** (ctime) of all files (excluding .DS_Store)
3. **Create directory structure** organized by month/day based on creation time
4. **Move files** to appropriate directories
5. **Create metadata analysis files** in each directory

### Expected Output

#### Directory Structure

Create directories in the format: `MM/DD/` where:

- MM = month (two digits, e.g., 01, 02)
- DD = day (two digits, e.g., 07, 09, 11, 26)

#### Metadata Analysis Files

Create a file named `metadata_analyse.txt` in each directory containing exactly only two lines:

- **Line 1**: Oldest filename and its creation time (excluding .DS_Store)
- **Line 2**: Latest filename and its creation time (excluding .DS_Store)
