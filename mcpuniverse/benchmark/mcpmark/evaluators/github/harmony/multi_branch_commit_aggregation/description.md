I need you to create a comprehensive commit history report by aggregating changes from multiple branches. Here's what you need to do:

**Step 1: Create Analysis Branch**
Create a new branch called 'history-report-2025' from the main branch.

**Step 2: Generate Branch Commits Report**
In the 'history-report-2025' branch, create a file called `BRANCH_COMMITS.json` that contains a JSON object with the following structure:
- For each of these branches: ['pr/45-googlefan256-main', 'pr/25-neuralsorcerer-patch-1', 'pr/41-amirhosseinghanipour-fix-race-conditions-and-offline-api']
- List the 3 most recent commits for each branch
- Each commit must include: SHA, GitHub username, commit message, and files changed count
- The JSON structure should be:
```json
{
  "pr/45-googlefan256-main": [
    {
      "sha": "commit_sha",
      "author": "github_username",
      "message": "commit message",
      "files_changed": number
    }
  ],
  "pr/25-neuralsorcerer-patch-1": [...],
  "pr/41-amirhosseinghanipour-fix-race-conditions-and-offline-api": [...]
}
```

**Step 3: Create Cross-Branch Analysis**
Create a file `CROSS_BRANCH_ANALYSIS.md` that contains:
- A section "## Top Contributors" listing the 3 contributors with the most commits on the main branch, sorted by commit count (format: "github_username: X commits")
- Must include keywords: "contributors"

**Step 4: Generate Merge Timeline**
Create a file `MERGE_TIMELINE.txt` that lists the 10 most recent merge commits from the main branch:
- Format: `DATE | MERGE_COMMIT_MESSAGE | COMMIT_SHA`
- List in reverse chronological order (newest first)
- Only include actual merge commits (commits that have exactly 2 parent commits)
- Note: While the commit messages reference PR numbers, those PRs no longer exist in the repository