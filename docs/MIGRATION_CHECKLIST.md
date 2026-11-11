# Policy Domino NEXT — production storage migration

The canonical v1 official-source ledger is retained as input to the v2
content-addressed migration. This file triggers a single on-repository
`[state-migrate]` workflow. No separate experimental repository is created.

## Required production checks

1. Read every existing v1 document, version, finding, public service, and AI
   review from the committed canonical source ledger.
2. Write immutable SHA-256 clause packs and version references as v2 state.
3. Rehydrate the complete v2 state and require **strict equality** with the
   original state before accepting the migration.
4. Run the official evidence contract and independently report incomplete
   source coverage. Neither passing CI nor migration changes a pending source
   into a verified legal amendment.
5. Persist only compressed canonical v2 sources. Do not recommit the removed
   42 MB public monolith. Website output is produced at deploy time as a
   compact index, a searchable source index, and per-event details.
6. Verify that a subsequent refresh adds only new immutable content packs
   when original text changes; unchanged content packs are never rewritten.

The action is declared successful only after GitHub Actions finishes and the
new state is actually committed. A source-coverage completeness claim is
independent of storage-migration success.
