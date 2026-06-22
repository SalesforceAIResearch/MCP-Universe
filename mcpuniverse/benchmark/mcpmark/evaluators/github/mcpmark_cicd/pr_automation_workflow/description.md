I need you to create a comprehensive Pull Request automation workflow for this Node.js project. The project currently has no GitHub Actions workflows, so you'll be building a PR-focused CI/CD workflow from scratch that responds to pull request events. Here's what needs to be implemented:

## Pull Request Automation Workflow

Create `.github/workflows/pr-automation.yml` that triggers on `pull_request` events (opened, synchronize, reopened) with these jobs:

### 1. **code-quality** job (name: `code-quality`):
  - Runs ESLint checks using `npm run lint`
  - Runs Prettier formatting checks
  - Posts code quality results as PR comment (must include keywords: "Code Quality Report", "ESLint", "Prettier")

### 2. **testing-suite** job (name: `testing-suite`):
  - Runs full test suite with `npm test`
  - Generates test coverage report
  - Posts coverage summary as PR comment (must include keywords: "Test Coverage Report")
  - Uploads coverage artifacts

### 3. **security-scan** job (name: `security-scan`):
  - Runs dependency vulnerability checks
  - Scans for secrets in code changes
  - Creates security report as PR comment (must include keywords: "Security Scan Report", "Vulnerabilities", "Dependencies")

### 4. **build-validation** job (name: `build-validation`):
  - Attempts to build the application
  - Validates all endpoints are accessible
  - Creates deployment preview artifacts
  - Posts build status as PR comment (must include keywords: "Build Validation")

**IMPORTANT: All four jobs must run in parallel.**

## Implementation Requirements:

**Step 1: Create Feature Branch**
Create a new branch called `pr-automation-workflow` from main.

**Step 2: Create the Workflow**
Create `.github/workflows/pr-automation.yml` with proper YAML syntax:
- Appropriate triggers for pull_request events
- All four jobs configured to run in parallel
- Avoid identifier conflicts in github-script actions

**Step 3: Create and Merge Pull Request**
Create a comprehensive pull request and merge it to main:
- Title: "Implement Pull Request Automation Workflow"
- Detailed description of the workflow and its purpose
- Merge the pull request to main branch

## Important Notes:

- **All jobs MUST run in parallel**
- Ensure your PR satisfies ALL required checks
- The workflow should handle edge cases, have proper error recovery, and provide clear logging