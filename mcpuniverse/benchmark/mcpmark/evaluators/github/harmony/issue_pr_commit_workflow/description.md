I need you to implement a complete bug tracking and resolution workflow that demonstrates proper cross-referencing between issues, pull requests, and commits. Here's what you need to do:

**Step 1: Create Issue for Race Condition Bug**
Create a new issue with:
- Title containing: 'race condition', 'HarmonyEncoding', 'concurrent access'
- Body must include:
  - A "## Problem" heading describing threading issues
  - A "## Root Cause" heading about file locking
  - A "## Expected Solution" heading with bullet points
  - References to issues #6 and #1
  - Keywords: "multiple threads", "tokenizer file downloads", "mutex-based file locking"

**Step 2: Create Feature Branch**
Create a new branch called 'fix/race-condition-tokenizer-loading' from main.

**Step 3: Implement Thread-Safe Loading**
On the feature branch, create/update the file `src/concurrent_loading.rs` with:
```rust
use std::sync::Mutex;
use std::sync::OnceLock;

// Thread-safe tokenizer loading with file locks
static DOWNLOAD_MUTEX: OnceLock<Mutex<()>> = OnceLock::new();

pub fn load_harmony_encoding_safe(name: &str) -> Result<HarmonyEncoding, HarmonyError> {
    let _guard = DOWNLOAD_MUTEX.get_or_init(|| Mutex::new(())).lock().unwrap();
    // Implementation for thread-safe loading
    // Addresses race condition from issue #6
    Ok(HarmonyEncoding::new())
}

pub fn load_harmony_encoding_from_file(path: &str) -> Result<HarmonyEncoding, HarmonyError> {
    // Offline loading API as requested in issue #1
    HarmonyEncoding::from_file(path)
}
```

**Step 4: Create Pull Request with Cross-References**
Create a pull request from 'fix/race-condition-tokenizer-loading' to 'main' with:
- Title containing: 'Fix race condition', 'tokenizer loading', 'threading issues'
- Body must include:
  - A "## Summary" heading explaining the fix
  - A "## Changes" heading with bullet points about mutex implementation
  - A "## Testing" heading mentioning related issues
  - "Closes #[ISSUE_NUMBER]" pattern linking to your created issue
  - References to #1 and #6
  - Keywords: "thread-safe", "concurrent downloads", "offline loading API"

**Step 5: Add PR Review Comments**
Create a pending review and add a review comment to the PR with:
- Technical analysis of the implementation approach
- Discussion of thread safety mechanisms
- Keywords that must be included: "OnceLock", "mutex", "thread safety", "concurrent access"
- Reference to issue #1 and the offline loading capability
- Explanation of how the solution prevents race conditions
Then submit the review as a COMMENT type review.

**Step 6: Update Issue with Implementation Details**
Add a comment to the original issue you created with:
- Reference to the PR number using "PR #[NUMBER]" pattern
- Technical details about the mutex-based solution
- Keywords: "std::sync::Mutex", "OnceLock", "thread-safe initialization"
- Mention of key implementation changes (DOWNLOAD_MUTEX, offline loading)
- Reference back to issue #1 for offline loading requirement

**Step 7: Close the Issue**
Close the issue you created by updating its state to 'closed' with state_reason 'completed'.