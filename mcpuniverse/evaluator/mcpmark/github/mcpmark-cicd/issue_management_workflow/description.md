I need you to create an intelligent Issue Management automation workflow for this Node.js project. The project currently has no GitHub Actions workflows, so you'll be building an issue-focused automation system from scratch that responds to issue events. Here's what needs to be implemented:

## Issue Management Workflow

Create `.github/workflows/issue-automation.yml` that triggers on `issues` events (opened, labeled) with these jobs:

### 1. **issue-triage** job:
   - Auto-assigns category labels based on keywords in **issue title** (case-insensitive):
     - Title contains "bug" → adds `bug` label
     - Title contains "epic" → adds `epic` label  
     - Title contains "maintenance" → adds `maintenance` label
   - Auto-assigns priority labels based on keywords in **issue title OR body** (case-insensitive, highest priority wins if multiple keywords found):
     - "critical", "urgent", "production", "outage" → `priority-critical`
     - "important", "high", "blocking" → `priority-high` 
     - "medium", "normal" → `priority-medium` (default if no priority keywords found)
     - "low", "nice-to-have", "minor" → `priority-low`
   - All issues get `needs-triage` label initially

### 2. **task-breakdown** job:
   - For issues with a title containing "Epic", create exactly 4 sub-issues with the pattern: "[SUBTASK] [Original Title] - Task N: [Task Name]"
   - Task names: 1. Requirements Analysis, 2. Design and Architecture, 3. Implementation, 4. Testing and Documentation
   - Links sub-issues to parent using "Related to #[parent-number]" in sub-issue body
   - Updates parent issue body with "## Epic Tasks" checklist linking to sub-issue numbers
   - All sub-issues get `enhancement` and `needs-review` labels

### 3. **auto-response** job:
   - Checks if the issue author is creating their first issue in this repository (not first on GitHub globally, but first in this specific repo)
   - If first issue in repo: adds `first-time-contributor` label and posts welcome message
   - Posts different responses based on issue type:
     - `bug` issues: comment must contain "Bug Report Guidelines"
     - `epic` issues: comment must contain "Feature Request Process"  
     - `maintenance` issues: comment must contain "Maintenance Guidelines"
   - Sets milestone "v1.0.0" for `priority-high` and `priority-critical` issues
   - Changes status from `needs-triage` to `needs-review` after response

## Label Management Requirements

The system must create and manage these specific labels:

### Category Labels:
- `bug` - Something isn't working
- `enhancement` - New feature or request  
- `epic` - Large feature requiring multiple sub-tasks
- `maintenance` - Maintenance and housekeeping tasks

### Priority Labels:
- `priority-critical` - Critical priority issue
- `priority-high` - High priority issue  
- `priority-medium` - Medium priority issue
- `priority-low` - Low priority issue

### Status Labels:
- `needs-triage` - Needs to be reviewed by maintainers
- `needs-review` - Awaiting review from maintainers
- `first-time-contributor` - Issue created by first-time contributor

## Implementation Requirements:

**Step 1: Create Feature Branch**
Create a new branch called `issue-management-workflow` from main.

**Step 2: Create Supporting Files**
Create these additional files on the new branch:
- `.github/ISSUE_TEMPLATE/bug_report.md` - Bug report template
- `.github/ISSUE_TEMPLATE/feature_request.md` - Feature request template
- `.github/ISSUE_TEMPLATE/maintenance_report.md` - Maintenance report template


**Step 3: Implement the Workflow**  
Create `.github/workflows/issue-automation.yml` with proper YAML syntax.  
Include:  
- Appropriate triggers for issues events  
- Job dependencies where needed  
- Error handling and graceful fallbacks  
- Avoid identifier conflicts in github-script actions (don't redeclare 'github')

**Step 4: Create and Merge Pull Request**
Create a comprehensive pull request and merge it to main:
- Title: "Implement Issue Management Automation Workflow"
- Detailed description of the workflow and its purpose
- Include all workflow files and templates created
- Merge the pull request to main branch

**Step 5: Test the Workflow**
Create test issues to demonstrate the issue automation workflow:

1. **Bug Issue**: "Bug: Login form validation not working"
   - Expected: `bug`, `priority-high`, `needs-triage`→`needs-review`, milestone "v1.0.0"
   - Auto-response comment must contain "Bug Report Guidelines"

2. **Epic Issue**: "Epic: Redesign user dashboard interface"
   - Expected: `epic`, `priority-high`, `needs-triage`→`needs-review`, milestone "v1.0.0"
   - Must create 4 sub-issues with `enhancement` and `needs-review` labels
   - Parent updated with "## Epic Tasks" checklist, sub-issues linked with "Related to #[parent-number]"
   - Auto-response comment must contain "Feature Request Process"

3. **Maintenance Issue**: "Weekly maintenance cleanup and refactor"  
   - Expected: `maintenance`, `priority-medium`, `needs-triage`→`needs-review`, no milestone
   - Auto-response comment must contain "Maintenance Guidelines"