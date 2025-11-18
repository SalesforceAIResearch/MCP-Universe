"""
Custom evaluator functions for MCPMark GitHub tasks.

These functions adapt verification logic from mcpmark/tasks/github/*/verify.py
into the MCP-Universe evaluator framework.
"""
# pylint: disable=line-too-long,import-outside-toplevel,duplicate-code
from __future__ import annotations

from typing import Tuple
from mcpuniverse.evaluator.functions import compare_func


##################################################################################
# Build Your Own X - Find Commit Date
##################################################################################

@compare_func(name="mcpmark_github.verify_commit_date")
async def verify_commit_date(_x: dict, *_args, **_kwargs) -> Tuple[bool, str]:
    """
    Verify the find commit date task for Voxel Engine entries.

    Adapted from: mcpuniverse/evaluator/mcpmark/github/build_your_own_x/find_commit_date/verify.py

    Checks:
    - ANSWER.md exists in the repository
    - Content format is correct (YYYY-MM-DD)
    - Date matches expected creation date (2018-07-07)
    - README.md contains Voxel Engine section
    - Voxel Engine entries are present
    """
    from mcpuniverse.evaluator.mcpmark.github.build_your_own_x.find_commit_date.verify import verify

    # Call the verify function
    passed, error_msg = verify()
    return passed, error_msg


##################################################################################
# Build Your Own X - Find RAG Commit
##################################################################################

@compare_func(name="mcpmark_github.verify_rag_commit")
async def verify_rag_commit(_x: dict, *_args, **_kwargs) -> Tuple[bool, str]:
    """
    Verify the find RAG commit SHA task.

    Adapted from: mcpuniverse/evaluator/mcpmark/github/build_your_own_x/find_rag_commit/verify.py

    Checks:
    - ANSWER.md exists in the repository
    - Content matches expected commit SHA (048cd3b3de70e4b429057891576ea394a50cdf48)
    - Commit exists in the repository
    - Commit message is accessible
    """
    from mcpuniverse.evaluator.mcpmark.github.build_your_own_x.find_rag_commit.verify import verify

    # Call the verify function
    passed, error_msg = verify()
    return passed, error_msg


##################################################################################
# Claude Code - Automated Changelog Generation
##################################################################################

@compare_func(name="mcpmark_github.verify_automated_changelog")
async def verify_automated_changelog(_x: dict, *_args, **_kwargs) -> Tuple[bool, str]:
    """
    Verify the automated changelog generation task.

    Adapted from: mcpuniverse/evaluator.mcpmark.github.claude_code.automated_changelog_generation.verify import verify

    Checks:
    - Documentation branch exists
    - CHANGELOG-GENERATED.md with proper sections and bug references
    - MIGRATION_GUIDE.md with open PR references
    - ISSUE_ANALYSIS.md with required sections
    - PR_INTEGRATION_PLAN.md with PR analysis
    - Documentation PR created and merged with squash method
    """
    from mcpuniverse.evaluator.mcpmark.github.claude_code.automated_changelog_generation.verify import verify

    # Call the verify function
    passed, error_msg = verify()
    return passed, error_msg


##################################################################################
# Claude Code - Claude Collaboration Analysis
##################################################################################

@compare_func(name="mcpmark_github.verify_claude_collaboration")
async def verify_claude_collaboration(_x: dict, *_args, **_kwargs) -> Tuple[bool, str]:
    """
    Verify the Claude collaboration analysis task.

    Adapted from: mcpuniverse.evaluator.mcpmark.github.claude_code.claude_collaboration_analysis.verify import verify

    Checks:
    - CLAUDE_COLLABORATION_ANALYSIS.md exists in main branch
    - Required sections present (Summary Statistics, Top Collaborators)
    - Summary statistics match expected values (158 commits, 25 Claude collaborations, 15.82%, 6 collaborators)
    - Top 3 collaborators identified with correct collaboration counts
    - Commit message verification
    """
    from mcpuniverse.evaluator.mcpmark.github.claude_code.claude_collaboration_analysis.verify import verify

    # Call the verify function
    passed, error_msg = verify()
    return passed, error_msg


##################################################################################
# Claude Code - Critical Issue Hotfix Workflow
##################################################################################

@compare_func(name="mcpmark_github.verify_critical_hotfix_workflow")
async def verify_critical_hotfix_workflow(_x: dict, *_args, **_kwargs) -> Tuple[bool, str]:
    """
    Verify the critical issue hotfix workflow task.

    Adapted from: mcpuniverse.evaluator.mcpmark.github.claude_code.critical_issue_hotfix_workflow.verify import verify

    Checks:
    - Hotfix branch exists (hotfix/memory-optimization-v1.0.72)
    - MEMORY_OPTIMIZATION.md documentation with exact content sections
    - Tracking issue created with proper title, headings, and issue references
    - Hotfix PR created with correct title, headings, and addresses pattern
    - PR #51 updated and merged
    - Tracking issue has implementation comment with PR references
    - Tracking issue closed
    """
    from mcpuniverse.evaluator.mcpmark.github.claude_code.critical_issue_hotfix_workflow.verify import verify

    # Call the verify function
    passed, error_msg = verify()
    return passed, error_msg


##################################################################################
# Claude Code - Feature Commit Tracking
##################################################################################

@compare_func(name="mcpmark_github.verify_feature_commit_tracking")
async def verify_feature_commit_tracking(_x: dict, *_args, **_kwargs) -> Tuple[bool, str]:
    """
    Verify the feature commit tracking task.

    Adapted from: mcpuniverse.evaluator.mcpmark.github.claude_code.feature_commit_tracking.verify import verify

    Checks:
    - FEATURE_COMMITS.md exists in main branch
    - Required sections present (Overview, Feature Commit History)
    - Feature table with correct format and at least 3 features
    - Expected commit SHAs for Shell Completion Scripts, CHANGELOG v1.0.65, Rust Extraction
    - Commit details verified (author, message, date format)
    - All commit SHAs exist in repository
    """
    from mcpuniverse.evaluator.mcpmark.github.claude_code.feature_commit_tracking.verify import verify

    # Call the verify function
    passed, error_msg = verify()
    return passed, error_msg


##################################################################################
# Claude Code - Label Color Standardization
##################################################################################

@compare_func(name="mcpmark_github.verify_label_color_standardization")
async def verify_label_color_standardization(_x: dict, *_args, **_kwargs) -> Tuple[bool, str]:
    """
    Verify the label color standardization task.

    Adapted from: mcpuniverse.evaluator.mcpmark.github.claude_code.label_color_standardization.verify import verify

    Checks:
    - Feature branch exists (feat/label-color-guide)
    - LABEL_COLORS.md documentation with proper table format
    - Issue created with required title keywords and content sections
    - PR created with proper title, body sections, and issue reference
    - Issue has all expected labels applied (21+ labels)
    - Issue has comment documenting changes with PR reference
    - All expected labels documented in the guide
    """
    from mcpuniverse.evaluator.mcpmark.github.claude_code.label_color_standardization.verify import verify

    # Call the verify function
    passed, error_msg = verify()
    return passed, error_msg


##################################################################################
# EasyR1 - Advanced Branch Strategy
##################################################################################

@compare_func(name="mcpmark_github.verify_advanced_branch_strategy")
async def verify_advanced_branch_strategy(_x: dict, *_args, **_kwargs) -> Tuple[bool, str]:
    """
    Verify the advanced branch strategy task.

    Adapted from: mcpuniverse/evaluator.mcpmark.github.easyr1.advanced_branch_strategy.verify import verify

    Checks:
    - GitFlow branch structure (develop, release/v1.0.0, feature/protocol-serialization-fix)
    - PROTOCOL_FIXES.md file with correct content
    - Integration PR from feature to develop
    - Release branch updated with develop changes
    - Process documentation issue with required checkboxes and labels
    """
    from mcpuniverse.evaluator.mcpmark.github.easyr1.advanced_branch_strategy.verify import verify

    # Call the verify function
    passed, error_msg = verify()
    return passed, error_msg


##################################################################################
# EasyR1 - Config Parameter Audit
##################################################################################

@compare_func(name="mcpmark_github.verify_config_parameter_audit")
async def verify_config_parameter_audit(_x: dict, *_args, **_kwargs) -> Tuple[bool, str]:
    """
    Verify the config parameter audit task.

    Adapted from: mcpuniverse/evaluator.mcpmark.github.easyr1.config_parameter_audit.verify import verify

    Checks:
    - ANALYSIS_RESULTS.json file exists and is valid
    - Commit data accuracy (SHA, author, date)
    - Parameter changes accuracy (micro_batch_size_per_device_for_update: 4→1, micro_batch_size_per_device_for_experience: 16→2)
    - Issue references contain required keywords (oom, memory, batch, 显存)
    """
    from mcpuniverse.evaluator.mcpmark.github.easyr1.config_parameter_audit.verify import verify

    # Call the verify function
    passed, error_msg = verify()
    return passed, error_msg


##################################################################################
# EasyR1 - Performance Regression Investigation
##################################################################################

@compare_func(name="mcpmark_github.verify_performance_regression_investigation")
async def verify_performance_regression_investigation(_x: dict, *_args, **_kwargs) -> Tuple[bool, str]:
    """
    Verify the performance regression investigation task.

    Adapted from: mcpuniverse.evaluator.mcpmark.github.easyr1.performance_regression_investigation.verify import verify

    Checks:
    - Main tracking issue with exact title and labels (bug, performance, investigation)
    - 3 investigation branches (investigate-protocol-changes, investigate-batch-processing, investigate-memory-usage)
    - 3 sub-issues with expected titles
    - Issue comments with file references (verl/protocol.py, examples/config.yaml, commit SHA)
    - Analysis PR with exact title from correct branch
    """
    from mcpuniverse.evaluator.mcpmark.github.easyr1.performance_regression_investigation.verify import verify

    # Call the verify function
    passed, error_msg = verify()
    return passed, error_msg


##################################################################################
# EasyR1 - Qwen3 Issue Management
##################################################################################

@compare_func(name="mcpmark_github.verify_qwen3_issue_management")
async def verify_qwen3_issue_management(_x: dict, *_args, **_kwargs) -> Tuple[bool, str]:
    """
    Verify the Qwen3 issue management task.

    Adapted from: mcpuniverse.evaluator.mcpmark.github.easyr1.qwen3_issue_management.verify import verify

    Checks:
    - All Qwen3 issues reopened and tagged with 'qwen3-related' label
    - Summary issue created with proper content and structure
    - All reopened issues listed in summary
    - Summary issue tagged with 'qwen3-related' label
    """
    from mcpuniverse.evaluator.mcpmark.github.easyr1.qwen3_issue_management.verify import verify

    # Call the verify function
    passed, error_msg = verify()
    return passed, error_msg


##################################################################################
# Harmony - Fix Conflict
##################################################################################

@compare_func(name="mcpmark_github.verify_fix_conflict")
async def verify_fix_conflict(_x: dict, *_args, **_kwargs) -> Tuple[bool, str]:
    """
    Verify the fix conflict task.

    Adapted from: mcpuniverse.evaluator.mcpmark.github.harmony.fix_conflict.verify import verify

    Checks:
    - CI infrastructure file exists in main branch
    - Infrastructure PR with required title and body content
    - Infrastructure PR is merged
    - PR #24 is merged
    - PR #24 has comment linking to infrastructure PR
    """
    from mcpuniverse.evaluator.mcpmark.github.harmony.fix_conflict.verify import verify

    # Call the verify function
    passed, error_msg = verify()
    return passed, error_msg


##################################################################################
# Harmony - Issue PR Commit Workflow
##################################################################################

@compare_func(name="mcpmark_github.verify_issue_pr_commit_workflow")
async def verify_issue_pr_commit_workflow(_x: dict, *_args, **_kwargs) -> Tuple[bool, str]:
    """
    Verify the issue PR commit workflow task.

    Adapted from: mcpuniverse.evaluator.mcpmark.github.harmony.issue_pr_commit_workflow.verify import verify

    Checks:
    - Feature branch exists (fix/race-condition-tokenizer-loading)
    - Rust implementation file with required content
    - Issue with required title, headings, and keywords
    - PR with required title, headings, and cross-references
    - PR review comments with technical keywords
    - Issue comments referencing PR with technical details
    - Issue is closed
    """
    from mcpuniverse.evaluator.mcpmark.github.harmony.issue_pr_commit_workflow.verify import verify

    # Call the verify function
    passed, error_msg = verify()
    return passed, error_msg


##################################################################################
# Harmony - Issue Tagging PR Closure
##################################################################################

@compare_func(name="mcpmark_github.verify_issue_tagging_pr_closure")
async def verify_issue_tagging_pr_closure(_x: dict, *_args, **_kwargs) -> Tuple[bool, str]:
    """
    Verify the issue tagging PR closure task.

    Adapted from: mcpuniverse.evaluator.mcpmark.github.harmony.issue_tagging_pr_closure.verify import verify

    Checks:
    - Feature branch exists (feat/esm-migration-attempt)
    - ESM implementation files with required content
    - Issue with required title, headings, keywords, and labels
    - PR with required title, headings, keywords, and labels
    - PR is closed without merging
    - PR technical analysis comment with required keywords
    - Issue comment referencing PR with required keywords
    - PR closure comment with required keywords
    - Issue is closed with closure comment
    """
    from mcpuniverse.evaluator.mcpmark.github.harmony.issue_tagging_pr_closure.verify import verify

    # Call the verify function
    passed, error_msg = verify()
    return passed, error_msg


##################################################################################
# Harmony - Multi Branch Commit Aggregation
##################################################################################

@compare_func(name="mcpmark_github.verify_multi_branch_commit_aggregation")
async def verify_multi_branch_commit_aggregation(_x: dict, *_args, **_kwargs) -> Tuple[bool, str]:
    """
    Verify the multi branch commit aggregation task.

    Adapted from: mcpuniverse.evaluator.mcpmark.github.harmony.multi_branch_commit_aggregation.verify import verify

    Checks:
    - Analysis branch exists (history-report-2025)
    - BRANCH_COMMITS.json with correct structure and expected data
    - CROSS_BRANCH_ANALYSIS.md with required sections and contributor data
    - MERGE_TIMELINE.txt with correct format and expected merge commits
    """
    from mcpuniverse.evaluator.mcpmark.github.harmony.multi_branch_commit_aggregation.verify import verify

    # Call the verify function
    passed, error_msg = verify()
    return passed, error_msg


##################################################################################
# Harmony - Release Management Workflow
##################################################################################

@compare_func(name="mcpmark_github.verify_release_management_workflow")
async def verify_release_management_workflow(_x: dict, *_args, **_kwargs) -> Tuple[bool, str]:
    """
    Verify the release management workflow task.

    Adapted from: mcpuniverse.evaluator.mcpmark.github.harmony.release_management_workflow.verify

    Checks:
    - Release branch exists (release-v1.1.0)
    - MetaSep token fix in encoding.rs
    - MetaSep and MetaEnd registry additions
    - Utils.ts file with correct content
    - .gitignore update
    - Version update in Cargo.toml
    - CHANGELOG.md with required content
    - Release PR merged using squash and merge method
    """
    from mcpuniverse.evaluator.mcpmark.github.harmony.release_management_workflow.verify import verify

    # Call the verify function
    passed, error_msg = verify()
    return passed, error_msg


##################################################################################
# MCPMark-CICD - Deployment Status Workflow
##################################################################################

@compare_func(name="mcpmark_github.verify_deployment_status_workflow")
async def verify_deployment_status_workflow(_x: dict, *_args, **_kwargs) -> Tuple[bool, str]:
    """
    Verify the deployment status workflow task.

    Adapted from: mcpuniverse.evaluator.mcpmark.github.mcpmark_cicd.deployment_status_workflow.verify import verify

    Checks:
    - Workflow runs with correct 3 sequential jobs: pre-deployment, rollback-preparation, post-deployment
    - Deployment tracking issue created and closed with proper labels
    - Issue contains rollback plan with all required elements
    - Previous and current commit SHAs are correctly tracked
    - All workflow automation comments are present
    """
    from mcpuniverse.evaluator.mcpmark.github.mcpmark_cicd.deployment_status_workflow.verify import verify

    # Call the verify function
    passed, error_msg = verify()
    return passed, error_msg


##################################################################################
# MCPMark-CICD - Issue Management Workflow
##################################################################################

@compare_func(name="mcpmark_github.verify_issue_management_workflow")
async def verify_issue_management_workflow(_x: dict, *_args, **_kwargs) -> Tuple[bool, str]:
    """
    Verify the issue management workflow task.

    Adapted from: mcpuniverse.evaluator.mcpmark.github.mcpmark_cicd.issue_management_workflow.verify import verify

    Checks:
    - Bug issue: labels (including first-time-contributor), milestone, and auto-response verified
    - Epic issue: labels, milestone, 4 sub-issues with checklist, and correct issue references verified
    - Maintenance issue: labels, no milestone, and auto-response verified
    - Issue templates created for bug reports, feature requests, and maintenance reports
    """
    from mcpuniverse.evaluator.mcpmark.github.mcpmark_cicd.issue_management_workflow.verify import verify

    # Call the verify function
    passed, error_msg = verify()
    return passed, error_msg


##################################################################################
# MCPMark-CICD - Linting CI Workflow
##################################################################################

@compare_func(name="mcpmark_github.verify_linting_ci_workflow")
async def verify_linting_ci_workflow(_x: dict, *_args, **_kwargs) -> Tuple[bool, str]:
    """
    Verify the linting CI workflow task.

    Adapted from: mcpuniverse.evaluator.mcpmark.github.mcpmark_cicd.linting_ci_workflow.verify import verify

    Checks:
    - ESLint configuration file (.eslintrc.json) with proper rules
    - GitHub Actions workflow file (.github/workflows/lint.yml) with correct triggers
    - Example file (src/example.js) with intentional linting violations
    - Pull request with proper structure and sections
    - Workflow execution: first commit fails, second commit passes after fixing errors
    """
    from mcpuniverse.evaluator.mcpmark.github.mcpmark_cicd.linting_ci_workflow.verify import verify

    # Call the verify function
    passed, error_msg = verify()
    return passed, error_msg


##################################################################################
# MCPMark-CICD - PR Automation Workflow
##################################################################################

@compare_func(name="mcpmark_github.verify_pr_automation_workflow")
async def verify_pr_automation_workflow(_x: dict, *_args, **_kwargs) -> Tuple[bool, str]:
    """
    Verify the PR automation workflow task.

    Adapted from: mcpuniverse.evaluator.mcpmark.github.mcpmark_cicd.pr_automation_workflow.verify import verify

    Checks:
    - Workflow file exists with correct triggers and 4 parallel jobs
    - Main PR was merged from pr-automation-workflow to main
    - Workflow runs show all 4 jobs executed in parallel and succeeded
    - PR comments contain required automation reports (Code Quality, Test Coverage, Security Scan, Build Validation)
    - Unit tests confirmed workflow correctly fails on problematic code
    """
    from mcpuniverse.evaluator.mcpmark.github.mcpmark_cicd.pr_automation_workflow.verify import verify

    # Call the verify function
    passed, error_msg = verify()
    return passed, error_msg


##################################################################################
# Missing Semester - Assign Contributor Labels
##################################################################################

@compare_func(name="mcpmark_github.verify_assign_contributor_labels")
async def verify_assign_contributor_labels(_x: dict, *_args, **_kwargs) -> Tuple[bool, str]:
    """
    Verify the assign contributor labels task.

    Adapted from: mcpuniverse.evaluator.mcpmark.github.missing_semester.assign_contributor_labels.verify import verify

    Checks:
    - Issues #9 and #14 have both 'assigned-jonhoo' and 'assigned-anishathalye' labels
    - Issue #15 and all 4 open PRs have 'assigned-anishathalye' label
    - Labels are assigned based on comments and top contributors from past 100 commits
    """
    from mcpuniverse.evaluator.mcpmark.github.missing_semester.assign_contributor_labels.verify import verify

    # Call the verify function
    passed, error_msg = verify()
    return passed, error_msg


##################################################################################
# Missing Semester - Find Legacy Name
##################################################################################

@compare_func(name="mcpmark_github.verify_find_legacy_name")
async def verify_find_legacy_name(_x: dict, *_args, **_kwargs) -> Tuple[bool, str]:
    """
    Verify the find legacy name task.

    Adapted from: mcpuniverse.evaluator.mcpmark.github.missing_semester.find_legacy_name.verify import verify

    Checks:
    - ANSWER.md exists in master branch
    - Content contains the legacy name 'Hacker Tools' and domain 'hacker-tools.github.io'
    - Format is correct: [Hacker Tools](https://hacker-tools.github.io)
    """
    from mcpuniverse.evaluator.mcpmark.github.missing_semester.find_legacy_name.verify import verify

    # Call the verify function
    passed, error_msg = verify()
    return passed, error_msg


##################################################################################
# Missing Semester - Find Salient File
##################################################################################

@compare_func(name="mcpmark_github.verify_find_salient_file")
async def verify_find_salient_file(_x: dict, *_args, **_kwargs) -> Tuple[bool, str]:
    """
    Verify the find salient file task.

    Adapted from: mcpuniverse.evaluator.mcpmark.github.missing_semester.find_salient_file.verify import verify

    Checks:
    - ANSWER.md exists in master branch
    - Content contains the most frequently modified file 'index.md'
    - Excludes GitHub Actions files from the analysis
    """
    from mcpuniverse.evaluator.mcpmark.github.missing_semester.find_salient_file.verify import verify

    # Call the verify function
    passed, error_msg = verify()
    return passed, error_msg
