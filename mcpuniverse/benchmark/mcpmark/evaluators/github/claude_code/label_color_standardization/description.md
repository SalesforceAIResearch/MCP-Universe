I need you to implement a comprehensive label documentation and organization workflow for the repository.

**Step 1: Create Label Documentation Issue**
Create a new issue with:
- Title containing: "Document label organization for better visual organization" and "label guide"
- Body must include:
  - A "## Problem" heading describing the need for better label documentation
  - A "## Proposed Solution" heading about creating a comprehensive label guide for different label categories
  - A "## Benefits" heading listing improved visual organization and easier issue triage
  - Keywords: "label documentation", "visual organization", "label guide", "organization"
- Labels: Initially add "enhancement" and "documentation" labels to the issue

**Step 2: Create Feature Branch**
Create a new branch called 'feat/label-color-guide' from main.

**Step 3: Create Label Documentation**
On the feature branch, create the file `docs/LABEL_COLORS.md` with:
- A "# Label Organization Guide" title
- A "## Label Categories" section with a table that MUST follow this exact format:
```markdown
| Label Name | Category | Description |
|------------|----------|-------------|
```
The table must include ALL existing labels in the repository. For each label:
- Group labels by category (e.g., issue-type, platform, area, status, performance)
- Include a description for each label

- A "## Usage Guidelines" section explaining when to use each label category

**Step 4: Apply ALL Labels to the Documentation Issue**
Update the issue you created in Step 1 by adding ALL existing labels from the repository. This serves as a visual demonstration of the label organization. The issue should have every single label that exists in the repository applied to it.

**Step 5: Create Pull Request**
Create a pull request from 'feat/label-color-guide' to 'main' with:
- Title containing: "Add label organization guide" and "visual organization"  
- Body must include:
  - A "## Summary" heading explaining the label organization documentation
  - A "## Changes" heading with a bullet list of what was added
  - "Fixes #[ISSUE_NUMBER]" pattern linking to your created issue
  - A "## Verification" section stating that all labels have been documented
  - Keywords: "label documentation", "organization guide", "visual improvement", "documentation"
- Labels: Add a reasonable subset of labels to the PR (at least 5-10 labels from different categories)

**Step 6: Document Changes in Issue**
Add a comment to the original issue with:
- Confirmation that the label documentation has been created
- Total count of labels documented
- Reference to the PR using "PR #[NUMBER]" pattern
- Keywords: "documentation created", "label guide complete", "organization complete"