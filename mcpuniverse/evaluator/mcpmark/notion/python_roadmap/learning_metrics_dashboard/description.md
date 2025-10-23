# Task: Learning Metrics Dashboard

## Objective
Create a comprehensive Learning Metrics Dashboard section in the Python Roadmap page that displays precise statistics and recommendations based on the Steps database content.

## Requirements

### 1. Section Placement
- Add new content immediately after the Learning Materials section (before `Whether you're starting from scratch or`).

### 2. Dashboard Header
- **Type**: heading_3
- **Text**: `📊 Learning Metrics Dashboard`

### 3. Course Statistics Block
- **Type**: callout
- **Background Color**: Brown
- **Icon**: None
- **Title**: **Course Statistics** (bold, heading_3). Use the same color scheme as other callout headings.
- **Content**: Bulleted list with the following items in exact order:
  - `Total Lessons: [X]` (count all entries in Steps database)
  - `Completed: [X] ([Y]%)` (count Status="Done", calculate percentage to 1 decimal)
  - `In Progress: [X] ([Y]%)` (count Status="In Progress", calculate percentage to 1 decimal)
  - `Beginner Level: [X] lessons ([Y] completed)` (filter by Chapters relation to Beginner Level)
  - `Intermediate Level: [X] lessons ([Y] completed)` (filter by Chapters relation to Intermediate Level)
  - `Advanced Level: [X] lessons ([Y] completed)` (filter by Chapters relation to Advanced Level)

### 4. Completed Topics Section
- **Type**: toggle
- **Text**: `🏆 Completed Topics (Click to expand)`
- **Nested Content**: Numbered list containing exactly 5 items
  - List lessons with Status="Done"