I have some pull requests that won't merge due to conflicts. Can you help me fix the merge conflicts by creating the missing infrastructure?

**Step 1: Find Conflicted PR**
Look through the open pull requests and find the one that has `mergeable: false` and `mergeable_state: "dirty"`. Check what file it's trying to modify - it appears to be missing a file that the PR is trying to add or modify.

**Step 2: Create Infrastructure PR**  
Create a new branch and PR to add the missing file that the conflicted PR needs. The PR must have:

- **Title**: Must contain "Add CI infrastructure" and "resolve conflicts"
- **Body**: Must include:
  - Reference to the conflicted PR using "Fixes #[PR_NUMBER]" or "Resolves #[PR_NUMBER]" 
  - Explanation that this "prepares infrastructure" for the other PR
  - Mention of "missing .github directory" and "workflow conflicts"
- **File Content**: Extract the complete file content from the conflicted PR's changes and add it to main. This ensures the conflicted PR can merge cleanly without conflicts.

**Step 3: Merge Infrastructure PR**
Merge the infrastructure PR to main.

**Step 4: Add Comment to Original PR**
Add a comment to the original conflicted PR that references the infrastructure PR you just created and merged. The comment must mention the infrastructure PR number using "PR #[NUMBER]" format.

**Step 5: Merge Original PR**
Now merge the original conflicted PR since it should be able to merge cleanly.