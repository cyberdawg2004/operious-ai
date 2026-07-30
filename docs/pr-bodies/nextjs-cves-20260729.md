Title: chore(deps): bump Next.js and eslint-config-next to 16.2.12 across frontends

Summary
- Bumped next and eslint-config-next to 16.2.12 in all frontend workspaces to remediate advisories affecting Next.js and related build tooling.

Files changed
- apps/marketing2/frontend/package.json
- apps/command-center2/frontend/package.json
- apps/platform-console/frontend/package.json
- package-lock.json (regenerated)

Testing
- npm ci && npm test && npm run build for each frontend workspace (verified locally: 131/131 tests passed)

Notes
- This is a patch/minor update intended to be low-risk. If integration tests show regressions, mark PR for further review and revert the merge if needed.
