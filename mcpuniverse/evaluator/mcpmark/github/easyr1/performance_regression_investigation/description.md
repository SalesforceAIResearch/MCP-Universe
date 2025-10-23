In the EasyR1 repo, I've discovered that the recent commit `098931530606d22f867fd121b1dcb3225a43661f` (which fixed data proto) may have introduced performance regressions based on user reports in issues #39 and #41. I need you to create a systematic investigation workflow:

**Step 1: Create Main Tracking Issue**
Create a main issue with the exact title "Performance Regression Analysis: Data Protocol Changes" and add these 3 labels: "bug", "performance", "investigation".

**Step 2: Create Investigation Branches** 
Create exactly 3 feature branches from main for different investigation tracks:
- `investigate-protocol-changes` - for testing protocol-related performance issues
- `investigate-batch-processing` - for testing batch processing performance issues  
- `investigate-memory-usage` - for testing memory utilization performance issues

**Step 3: Create Sub-Issues**
Create 3 sub-issues and link them to the main tracking issue using sub-issue functionality:
- "Test Performance Impact: fix multi modal data oom" 
- "Test Performance Impact: upgrade vllm to 0.10"
- "Test Performance Impact: non blocking false by default"

**Step 4: Document Changes**
Add at least 2 comments to the main tracking issue documenting the specific file changes from commit `098931530606d22f867fd121b1dcb3225a43661f`. Reference the exact files `verl/protocol.py` and `examples/config.yaml` with their commit SHA.

**Step 5: Create Analysis PR**
Create a pull request from the `investigate-protocol-changes` branch to main with the exact title "Performance Analysis: Protocol Changes Investigation".