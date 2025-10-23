The EasyR1 repository has a critical production issue: all development happens directly on the `main` branch, which is extremely risky for a project with 25 active issues. A recent commit `098931530606d22f867fd121b1dcb3225a43661f` introduced protocol changes that need to be properly managed through a structured branching workflow. I need you to implement a complete GitFlow strategy by working through a realistic development scenario.

**The Scenario:** You're preparing for the v1.0.0 release while simultaneously handling a critical protocol serialization bug that was introduced in the recent data proto changes.

**Step 1: Initialize GitFlow Structure**
Create a `develop` branch from `main` as the new integration branch. Then create a `release/v1.0.0` branch from `develop` to prepare for the upcoming release.

**Step 2: Address the Critical Bug**
Create a `feature/protocol-serialization-fix` branch from `develop`. In this branch, create a new file called `PROTOCOL_FIXES.md` with the exact content:
```
# Protocol Serialization Fixes

## Critical Fix for Data Proto Issue
- Enhanced serialization safety check implemented
- Addresses issue from commit 098931530606d22f867fd121b1dcb3225a43661f
- Status: Ready for integration testing
```

**Step 3: Integrate the Fix Through Proper Workflow**
Create a pull request from `feature/protocol-serialization-fix` to `develop` to integrate the fix documentation. This demonstrates the feature → develop integration pattern.

**Step 4: Update Release Branch and CI/CD**
Merge the develop branch changes into `release/v1.0.0` branch to include the critical fix in the release.

**Step 5: Document the New Process**
Create an issue titled `Implement Advanced Branch Protection Strategy` with exactly these 3 checkboxes in the body:
- [ ] All development flows through develop branch
- [ ] Release preparation happens in release/v1.0.0 branch  
- [ ] Feature integration uses PR workflow

Add the label `process-implementation` to this issue to track the process implementation.