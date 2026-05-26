# nest-marketplace

Data adapter for the NEST hackathon marketplace UI.

This package is a pure-Python adapter that:

1. Loads judge-panel scores from `docs/hackathon/scores.json` if present.
2. Fetches open `hackathon/*` pull requests via the GitHub REST API (or
   accepts a pre-fetched list, for tests and offline builds).
3. Tags each submission as `agent-authored` (one of the ten known agent
   handles in the branch slug) or `human-authored`.
4. Computes per-layer stats and serialises the result to a JSON shape
   the `apps/nest-dashboard` Next.js routes can consume directly.

The Next.js app reads the static JSON written by `nest-marketplace-build`
at build time so the public hackathon pages never hit GitHub at request
time and never leak secrets.
