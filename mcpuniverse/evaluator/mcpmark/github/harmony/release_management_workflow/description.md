I need help implementing a comprehensive release management workflow for this harmony repository. Here's what I need you to do:

**Step 1: Analyze Current State** 
First, analyze the current open pull requests to understand what changes they contain and their impact on the codebase.

**Step 2: Create Release Branch**
Create a release preparation branch called 'release-v1.1.0' from the current main branch.

**Step 3: Apply Critical Bug Fixes**
On the release branch, apply the MetaSep token fix from PR #25 by creating/updating the file `src/encoding.rs` with the corrected content where FormattingToken::MetaSep maps to "<|meta_sep|>" instead of "<|channel|>".

Also create/update `src/registry.rs` to include the missing MetaSep and MetaEnd token registrations:
```rust
(FormattingToken::MetaSep, "<|meta_sep|>"),
(FormattingToken::MetaEnd, "<|meta_end|>"),
```

**Step 4: Add Missing Utility File**
From PR #26, create the missing shadcn utils file `demo/harmony-demo/src/lib/utils.ts` with content:
```typescript
import { clsx, type ClassValue } from "clsx"
import { twMerge } from "tailwind-merge"

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs))
}
```

And create/update `.gitignore` to add:
```
# Avoid ignoring shadcn utils
!demo/harmony-demo/src/lib
```

**Step 5: Version Update**
Update the version number in `Cargo.toml`: Change the `version` field in the `[package]` section to `version = "1.1.0"`.

**Step 6: Create Comprehensive Changelog**
Create a `CHANGELOG.md` file in the release branch with the following content:
```markdown
# Changelog

## [1.1.0] - 2025-08-07

### Added
- Added missing shadcn utils.ts file for demo application
- Enhanced gitignore rules to preserve shadcn utilities

### Fixed
- Fixed MetaSep token mapping bug (was incorrectly mapped to channel token)
- Added missing MetaSep and MetaEnd token registrations in registry
- Improved tokenizer registry functionality for meta formatting tokens

### Changed
- Updated version to 1.1.0 for new release cycle

### Technical Details
- MetaSep token now correctly maps to `<|meta_sep|>` instead of `<|channel|>`
- Registry now properly recognizes MetaSep and MetaEnd formatting tokens
- Demo application now includes required utility functions for UI components
```

**Step 7: Create Release Pull Request**
Create a pull request from 'release-v1.1.0' to 'main' with title "Release v1.1.0 - Bug fixes and utility additions" and a detailed description explaining all the integrated changes.

**Step 8: Merge the Pull Request**
After creating the PR, merge it into the main branch using the "squash and merge" method.

**Step 9: Verification**
Ensure the release branch contains at least 4 distinct commits before merging:
1. MetaSep token fix commit
2. Utility file addition commit  
3. Version update commit
4. Changelog addition commit