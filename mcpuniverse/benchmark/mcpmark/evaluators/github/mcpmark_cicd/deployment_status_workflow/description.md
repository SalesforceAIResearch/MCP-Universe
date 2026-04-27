I need you to create a Deployment Status workflow for this Node.js project. The project currently has no GitHub Actions workflows, so you'll be building a deployment-focused CI/CD workflow from scratch that responds to push events on the main branch. Here's what needs to be implemented:

## Deployment Status Workflow

Create `.github/workflows/deployment-status.yml` that triggers on `push` to `main` branch with these sequential jobs:

### 1. **pre-deployment** job (name: `pre-deployment`):
   - Runs basic quality checks (lint and test)
   - Creates deployment tracking issue with title: "Deployment Tracking - [commit-sha]"
   - Adds labels: `deployment`, `in-progress`
   - Captures previous commit SHA and package version information
   - Posts comment containing "Pre-deployment checks completed"

### 2. **rollback-preparation** job (name: `rollback-preparation`):
   - Depends on: pre-deployment
   - Creates comprehensive rollback artifacts including:
     * Executable rollback script with proper error handling
     * Configuration backups (package.json, package-lock.json, environment templates)
     * Dependency verification script for compatibility checking
     * Detailed rollback documentation with step-by-step instructions
     * Compressed rollback package with SHA256 checksums
   - Uploads rollback artifacts to GitHub Actions with 30-day retention
   - Posts comment on deployment issue that MUST contain the following verifiable elements:
     * Title: "🔄 Rollback Plan Ready"
     * Previous commit SHA (format: "Previous Commit: [sha]")
     * Current commit SHA (format: "Current Commit: [sha]")
     * Package version (format: "Package Version: [version]")
     * Artifact name (format: "Artifact: rollback-package-[commit-sha]")
     * At least 5 checkmarks (✅) indicating completed rollback components
     * Quick rollback command section with bash code block
     * Script verification status: "Rollback script created: true"
     * Backup verification status: "Configuration backup: true"
     * Artifact checksum (format: "SHA256: [checksum-value]")

### 3. **post-deployment** job (name: `post-deployment`):
   - Depends on: rollback-preparation
   - Removes `in-progress` label and adds `completed` label
   - Posts final comment containing "Deployment Completed Successfully" with rollback artifact details
   - Closes the deployment tracking issue

## Implementation Requirements:

**Step 1: Create Feature Branch**
Create a new branch called `deployment-status-workflow` from main.

**Step 2: Implement the Workflow**
Create `.github/workflows/deployment-status.yml` with proper YAML syntax:
- Trigger only on push to main branch
- Sequential job execution: pre-deployment → rollback-preparation → post-deployment
- Use github-script actions for issue management
- Avoid identifier conflicts in github-script actions (don't redeclare 'github')
- Include proper error handling and script validation
- Implement comprehensive rollback artifact creation and verification
- Use proper fetch-depth for accessing commit history
- Include artifact upload/download capabilities with checksums

**Step 3: Create and Merge Pull Request**
Create a comprehensive pull request and merge it to main:
- Title: "Implement Deployment Status Workflow"
- Detailed description of the workflow and its purpose
- Merge the pull request to main branch to trigger the deployment workflow