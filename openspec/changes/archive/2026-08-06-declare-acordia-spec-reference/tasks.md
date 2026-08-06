## 1. Declaration

- [x] 1.1 Add a `references:` block to `openspec/config.yaml` naming store id `acordia` and its git remote, with a comment stating it is records-only and intentionally unregistered
- [x] 1.2 Confirm `openspec doctor` reports the reference (warning plus register recipe) instead of `(none declared)`

## 2. Verify what the declaration buys

- [x] 2.1 Read `dist/core/references.js` and record the finding: a reference indexes the referenced root's specs as read-only upstream context and runs no cross-root drift check; root resolution is unaffected
- [x] 2.2 Record the hazard that `openspec store register` writes `.openspec-store/store.yaml` into the store root, and the resulting decision to declare-not-register so the seam stays one-directional and nothing is written into acordia

## 3. Documentation

- [x] 3.1 Refresh the proposal: the consumer is acordia-analysts `2.1.0` selecting the seventeen unprefixed tool verbs, and answer the open question — the declaration records and indexes, it does not enforce
- [x] 3.2 Fold the deferred section in `docs/implementation-notes.md` down to a retired bullet pointing at the declaration
