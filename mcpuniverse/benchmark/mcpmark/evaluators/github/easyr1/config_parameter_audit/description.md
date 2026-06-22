I need you to perform a deep investigation into recent configuration changes in our EasyR1 repository that may be causing training instability issues.

## Task Requirements

### 1. Deep Commit Analysis
Find the exact commit SHA where the `micro_batch_size_per_device_for_update` parameter was changed from `4` to `1` in the `examples/config.yaml` file. Use GitHub API to:
- Examine recent commits that modified `examples/config.yaml` 
- Get the specific commit diff showing this parameter change
- Identify the commit author and timestamp

### 2. Related Parameter Investigation  
In the same commit you found above, identify what value the `micro_batch_size_per_device_for_experience` parameter was changed to. Document:
- The before value for this parameter
- The after value for this parameter  
- The specific line numbers in the diff where these changes occurred

### 3. Issue Search and Verification
Search through all GitHub issues (both open and closed) to find issues that contain specific keywords. Identify all issue numbers where the issue title or body text contains any of these exact terms:
- "OOM" (case insensitive)
- "memory" (case insensitive) 
- "batch" (case insensitive)
- "显存" (GPU memory in Chinese)

You must find and list ALL issues that contain any of these keywords in their titles or bodies, regardless of whether you think they're related to the parameter changes.

### 4. File Creation and Results
Create a file named exactly `ANALYSIS_RESULTS.json` in the repository root with this exact structure:

```json
{
  "target_commit_sha": "full-40-character-commit-sha",
  "commit_author": "author-username", 
  "commit_date": "YYYY-MM-DD",
  "parameter_changes": {
    "micro_batch_size_per_device_for_update": {
      "before": 4,
      "after": 1,
      "line_number": 123
    },
    "micro_batch_size_per_device_for_experience": {
      "before": 16,
      "after": 2, 
      "line_number": 124
    }
  },
  "related_issue_number_list": [9, 46]
}
```

### 5. Verification Requirements
- The commit SHA must be exactly 40 hexadecimal characters
- The parameter values must match the actual repository changes  
- The issue number must reference a real issue in the repository
- All data must be obtained through GitHub API analysis, not guesswork