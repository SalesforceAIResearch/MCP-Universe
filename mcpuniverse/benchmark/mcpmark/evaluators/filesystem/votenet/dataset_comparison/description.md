Please use FileSystem tools to finish the following task:

### Task Description

Analyze the codebase to map ScanNet object categories to SUN RGB-D categories and calculate object counts.

### Task Objectives

1. **Primary Goal**: Use SUN RGB-D's 10-category classification system as the target taxonomy
2. **Mapping Requirement**: Map each ScanNet object category (using the "category" field, not "raw_category") to the corresponding SUN RGB-D category
3. **Calculation**: For each SUN RGB-D category, calculate the total count of objects from ScanNet that map to that category （It only counts if the category (not raw category) name are exactly the same(night_stand = nightstand)）
4. **Output**: Generate an analysis.txt file in the main directory showing the mapping and counts

### Expected Output

Create a file named `analysis.txt` in the test directory root with the following format:

- Each SUN RGB-D category should be represented as a 2-line block
- Line 1: category name
- Line 2: total count
- Each block should be separated by one empty line
