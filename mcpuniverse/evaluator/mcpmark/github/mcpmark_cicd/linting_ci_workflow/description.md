I need you to set up a proper linting workflow for our CI pipeline to ensure code quality standards are enforced on all pull requests. Here's what you need to do:

**Step 1: Create Linting Configuration Branch**
Create a new branch called 'ci/add-eslint-workflow' from the main branch.

**Step 2: Create ESLint Configuration**
On the new branch, create the file `.eslintrc.json` in the repository root with:
```json
{
  "env": {
    "browser": true,
    "es2021": true,
    "node": true
  },
  "extends": [
    "eslint:recommended"
  ],
  "parserOptions": {
    "ecmaVersion": 12,
    "sourceType": "module"
  },
  "rules": {
    "no-unused-vars": "error",
    "no-console": "warn",
    "semi": ["error", "always"],
    "quotes": ["error", "single"]
  },
  "ignorePatterns": ["node_modules/", "dist/", "build/"]
}
```

**Step 3: Create GitHub Actions Linting Workflow**
Create the file `.github/workflows/lint.yml` with:
- Workflow name: "Code Linting"
- Triggers on: push to main, pull_request events
- Uses ubuntu-latest runner
- Sets up Node.js version 18 using actions/setup-node
- Installs dependencies with npm ci
- Installs ESLint globally
- Runs ESLint on all JavaScript files in src/ directories
- Fails the workflow if linting errors are found

**Step 4: Create a File That Will Fail Linting**
Create the file `src/example.js` with intentional linting violations that will cause the CI check to fail.

**Step 5: Create Pull Request**
Commit all the changes (ESLint config, workflow file, and example file with linting errors) in a single commit, then create a pull request from 'ci/add-eslint-workflow' to 'main' with:
- Title: "Add ESLint workflow for code quality enforcement"
- Body must include:
  - A "## Summary" heading describing the linting setup
  - A "## Changes" heading listing the files added
  - A "## Testing" heading explaining how to test the workflow
  - Mention that the PR intentionally includes linting errors to demonstrate the workflow

**Step 6: Fix Linting Errors and Update PR**
Fix the linting errors in `src/example.js` and commit the changes in a single commit to update the PR so that the CI check passes.

