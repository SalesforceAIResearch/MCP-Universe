I need you to analyze all recently closed issues and open pull requests in the repository, then generate comprehensive documentation and organize them properly.

**Step 1: Create Documentation Branch**
Create a new branch called 'docs/changelog-and-migration' from the main branch.

**Step 2: Generate Changelog from Closed Issues**
Find all closed issues in the repository and create the file `CHANGELOG-GENERATED.md` on your branch with:
- A heading "# Changelog - Recent Fixes"
- A "### 🐛 Bug Fixes" section listing all closed issues with bug label, formatted as: "- **#[NUMBER]**: [Title] ([labels])"
- A "### 📚 Documentation" section for closed issues with documentation label
- A "### 🔄 Duplicates" section for issues marked as duplicate
- A "### 📊 Statistics" section with:
  - Total number of closed issues
  - Distribution by platform labels (platform:macos, platform:linux, etc.)
  - Distribution by area labels (area:core, area:tools, etc.)

**Step 3: Create Migration Guide for Open PRs**
Analyze all open pull requests and create the file `docs/MIGRATION_GUIDE.md` with:
- A heading "# Migration Guide for Pending Features"
- For each open PR, create a section with:
  - PR title and number
  - Summary of changes based on the PR description
  - Any new configuration or environment variables mentioned
  - Installation or usage instructions if applicable

**Step 4: Create Issue Analysis Report**
Create the file `reports/ISSUE_ANALYSIS.md` with:
- A heading "# Issue Analysis Report"
- A "## Closed Issues by Category" section grouping closed issues by their primary label
- A "## Resolution Patterns" section identifying common themes
- A "## Platform Impact Analysis" section showing which platforms were most affected
- Include references to specific issues that had cross-project impact or memory-related problems

**Step 5: Create PR Integration Plan**
Create the file `reports/PR_INTEGRATION_PLAN.md` with:
- A heading "# Pull Request Integration Strategy"
- A "## Open PRs Overview" section listing each open PR with a technical summary
- A "## Dependencies and Conflicts" section analyzing potential conflicts between PRs
- A "## Recommended Merge Order" section with reasoning
- A "## Risk Assessment" section linking any risks to previously closed issues

**Step 6: Create Documentation PR**
Create a pull request from 'docs/changelog-and-migration' to 'main' with:
- Title: "docs: Generated changelog and migration documentation"
- Body including:
  - A "## Summary" section describing what was generated
  - A "## Files Created" section listing all new documentation
  - A "## Issues Processed" section mentioning the number of closed issues analyzed
  - A "## PRs Analyzed" section mentioning the open PRs reviewed

**Step 7: Merge Documentation PR**
Merge the documentation pull request using the "squash" merge method.