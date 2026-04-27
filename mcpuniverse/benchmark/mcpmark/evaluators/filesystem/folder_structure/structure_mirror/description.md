Please use FileSystem tools to finish the following task:

### Task

Copy the entire directory structure of `complex_structure/` to `complex_structure_mirror/` without copying any file contents. Do not use python code.

### Requirements

- Create the entire directory structure in `complex_structure_mirror/`
- Do not copy any file contents, only create directories
- In each empty directory, create a `placeholder.txt` file containing the absolute path of that directory
- Handle nested directories of any depth
- You should also follow 2 rules:
    1. **Discard any directory that directly contains more than 2 files (only count the immediate folder).**
    2. **If a directory name contains numbers, append "_processed" to the mirror directory name**
