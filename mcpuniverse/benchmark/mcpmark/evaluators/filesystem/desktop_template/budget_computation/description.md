Please use FileSystem tools to finish the following task:

### Task Description

You need to analyze all the files in the desktop environment to calculate personal life expenses and create a budget summary.

### Task Objectives

1. **Locate and analyze all files** in the desktop environment
2. **Extract personal life expenses** from the files (such as salary, food, living material, tax, expenses on the internet, ...) (exclude expenses in project/work)
3. **Create a file named `total_budget.txt`** in the main directory
4. **Format each expense entry** as `file_path;price` (one per line)
5. **Add total sum** as the last line, rounded to 2 decimal places

### Output Format

The `total_budget.txt` file should contain:

- One expense per line in format: `file_path;price`
- File path should be the relative path from the main directory
- Price should be rounded to 2 decimal places
- Last line should be the total sum
- No additional text or explanations

### Important Notes

- Only include personal life expenses (not in project/work)
- Use the cheapest available price when multiple options exist for one thing
- The total should match the sum of all individual expenses
- Hint: If a file contains 1 item for personal consumption, it means that all the entry in entire file is for personal consumption
