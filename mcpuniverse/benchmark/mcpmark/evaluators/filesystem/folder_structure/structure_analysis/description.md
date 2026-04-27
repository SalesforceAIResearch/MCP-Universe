Please use FileSystem tools to finish the following task:

You need to recursively traverse the entire folder structure under the main directory and generate a detailed statistical report in a file named `structure_analysis.txt`.

In all tasks, ignore `.DS_Store` files.

In any tasks, you should not change or delete any existed files.

Do not try to use python code.

---

### 1. File Statistics

Count the following information for the entire directory structure:

- total number of files
- total number of folders
- total size of the hole folder (in bytes, include .DS_Store only in this subtask)

**Format (one item per line):**

total number of files: X
total number of folders: Y
total size of all files: Z

---

### 2. Depth Analysis

Identify the deepest folder path(s) in the directory and calculate its depth level.

- Use relative paths based on main directory.
- **Write the folder path only up to the folder, not including the file name.For example, if the file path is `./complex_structure/A/B/C/def.txt`, then the path in your report should be `complex_structure/A/B/C`, and the depth is `4`.**
- If multiple deepest paths exist, list only one.

**Format (one item per line):**

depth: N
PATH

---

### 3. File Type Classification

Categorize files by their extensions and count the number of files for each type.
Files without extensions should also be included.

**Format (one extension per line):**

txt: count
py: count
jpg: count
mov: count
(no extension): count
