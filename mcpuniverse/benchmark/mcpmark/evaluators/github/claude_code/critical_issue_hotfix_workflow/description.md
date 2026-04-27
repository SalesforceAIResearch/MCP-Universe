I need you to implement a comprehensive critical issue hotfix workflow for the repository that demonstrates advanced PR management, selective merging, and issue resolution tracking.

**Step 1: Create Critical Bug Tracking Issue**
Create a new issue with:
- Title: "CRITICAL: Memory and Context Management Issues - Hotfix Tracking"
- Body must include:
  - A "## Critical Issues" heading listing issues #49 and #46
  - A "## Impact Assessment" heading describing user impact
  - A "## Resolution Strategy" heading with planned approach
  - References to existing issues #49, #46, and #47 using "#" notation
  - Keywords: "memory exhaustion", "context auto-compact", "JavaScript heap", "hotfix priority"

**Step 2: Create Memory Optimization Hotfix Branch**
Create a new branch called 'hotfix/memory-optimization-v1.0.72' from the main branch.

**Step 3: Implement Memory Management Documentation**
On the hotfix branch, create the file `docs/MEMORY_OPTIMIZATION.md` with this exact content:
```markdown
# Memory Optimization Guide for Claude Code v1.0.72

## Overview
This document addresses critical memory issues identified in issues #49 and #46.

## Memory Management Issues

### Context Auto-Compact Problem (Issue #49)
- **Root Cause**: Context management stuck at 0% completion
- **Impact**: Tool becomes unusable on macOS platforms
- **Solution**: Implement progressive context cleanup with configurable thresholds

### JavaScript Heap Exhaustion (Issue #46)
- **Root Cause**: Memory allocation failure during large MCP operations
- **Impact**: Complete Claude Code crash requiring restart
- **Solution**: Add streaming data processing and garbage collection optimization

## Optimization Strategies

### Immediate Fixes
1. **Context Buffer Management**
   - Implement 10MB default context buffer limit
   - Add automatic context pruning at 80% threshold
   - Enable manual context reset via `/memory-reset` command

2. **MCP Operation Streaming**
   - Process large datasets in 1MB chunks
   - Implement backpressure for MongoDB operations
   - Add memory usage monitoring and alerts

### Configuration Options
```json
{
  "memory": {
    "contextBufferLimit": "10MB",
    "autoCompactThreshold": 0.8,
    "streamingChunkSize": "1MB",
    "gcOptimization": true
  }
}
```

## Related Issues
- Fixes issue #49: Context auto-compact functionality
- Addresses issue #46: JavaScript heap out of memory crashes
- Related to issue #47: Cross-project hook execution problems
```
```

**Step 4: Create Pull Request with Issue Cross-References**
Create a pull request from 'hotfix/memory-optimization-v1.0.72' to 'main' with:
- Title: "HOTFIX: Critical memory optimization for issues #49 and #46"
- Body must include:
  - A "## Summary" heading describing the memory fixes
  - A "## Critical Issues Addressed" heading listing specific problems
  - A "## Documentation Changes" heading describing the new guide
  - "Addresses #49" and "Addresses #46" pattern linking to existing issues
  - Reference to your tracking issue using "Tracked in #[ISSUE_NUMBER]"
  - Keywords: "memory optimization", "context management", "heap exhaustion", "v1.0.72 hotfix"

**Step 5: Update and Merge PR #51 (Statsig Logging)**
For the existing PR #51:
- Update the PR description to include technical implementation details
- Add a "## Technical Implementation" section mentioning "event logging integration"
- Add keywords: "workflow enhancement", "issue management automation", "logging consistency"
- Merge the PR using the squash merge method

**Step 6: Add Implementation Comment to Tracking Issue**
Add a comment to your original tracking issue with:
- Reference to your hotfix PR using "PR #[NUMBER]" pattern
- Reference to actions taken on PR #51
- Technical details about the memory optimization approach
- Keywords: "context buffer management", "streaming optimization", "progressive cleanup"
- Mention of configuration options and thresholds

**Step 7: Close Tracking Issue with Resolution Summary**
Close your tracking issue by updating its state to 'closed' with:
- A final comment summarizing completed actions
- Reference to merged PR #51 and pending hotfix PR
- Keywords: "hotfix deployment", "memory issues resolved", "documentation updated"