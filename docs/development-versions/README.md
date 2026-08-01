# Development Version Records

This directory records Zebra branches that may feed a FinOS deployment. A chat,
worktree name, or moving label such as "latest" is not version evidence.

For the FinOS integration, the fixed deployment branch is
`vinson1101/zebra:codex/finos-runtime-alignment`. Feature branches, PR heads,
temporary worktrees, and detached commits must merge into that branch before
packaging. Changing the fixed deployment branch requires a documented migration
and a new FinOS/Zebra compatibility run; it cannot happen inside an ordinary
feature rollout.

Each development record must name the owner/task, repository, base branch and
full base commit, source branches and commits, merge commit, changed contracts,
owned scope, implementation head, exact validation results, inherited failures,
merge target, and remaining risks. Deployment is recorded only after rollout in
FinOS `docs/staging-environment.md`, with the final branch commit, image digest,
release directory, rollback point, smoke evidence, and data fingerprints.
