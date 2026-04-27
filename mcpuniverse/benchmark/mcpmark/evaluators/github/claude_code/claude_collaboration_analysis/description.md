I need you to analyze the collaboration patterns between human developers and Claude (the AI assistant) in the repository by examining all available commit history, then create a comprehensive analysis report and submit it as a new file to the repository.

**Step 1: Commit History Analysis**
Analyze ALL commits in the repository to identify:

1. **Claude Co-Authored Commits**: Find all commits that were co-authored by Claude (look for "Co-Authored-By: Claude <noreply@anthropic.com>" in commit messages)
2. **Top Claude Collaborators**: Identify the top 3 human developers who most frequently collaborated with Claude

**Step 2: Create Collaboration Analysis Report**
Create a file called `CLAUDE_COLLABORATION_ANALYSIS.md` in the repository root with:

- A "# Claude AI Collaboration Analysis" title
- A "## Summary Statistics" section with these exact format requirements:
  - "Total commits analyzed: [NUMBER]"
  - "Number of Claude co-authored commits found: [NUMBER]"
  - "Percentage of commits with Claude collaboration: [NUMBER]%"
  - "Number of unique human collaborators who worked with Claude: [NUMBER]"

- A "## Top Claude Collaborators" section with this exact table format:
```markdown
| Developer | GitHub Username | Claude Collaborations |
|-----------|----------------|----------------------|
```
Include the top 3 developers by number of Claude collaborations.

**Step 3: Commit Analysis to Repository**
Commit the `CLAUDE_COLLABORATION_ANALYSIS.md` file to the main branch with:
- Commit message: "Add Claude AI collaboration analysis report"
- Ensure all statistics are accurate based on actual commit data