# Combining the Codex and Claude work streams

The streams have not been merged. Keep Claude's original `/Users/dhaanish/Desktop/VIVA` untouched while it is active. This checkout has the copied implementation and a hash inventory in `coordination/baseline-manifest.json`. Baseline Git commit `975d674` captures tracked checkout files; the manifest is a separate record of the copied baseline, including files Git did not track. A hash alone cannot reconstruct old file contents.

## Inventory without modifying either stream

From the checkout root:

```sh
python3 coordination/compare_workstreams.py --output coordination/workstreams-report.json
python3 -m unittest discover -s coordination -p 'test_compare_workstreams.py' -v
```

Omit `--output` to print JSON. `--manifest`, `--codex` and `--claude` accept explicit paths for later snapshots. Output is rejected inside either source tree or over the manifest. The tool compares hashes and identifies Codex-only, Claude-only, converged and conflict paths; entries describe additions, modifications and deletions. A conflict means both changed differently, including edit/delete and independent additions; it is a review queue, not a semantic merge decision. Paths outside directories represented by the manifest are `unbaselined`: they may have existed before capture, and cannot be proven new. The original workspace contains such material. Review it separately if relevant.

Scans exclude dependency/runtime/build directories, environment files other than `.env.example`, databases, audio and common key files; the report includes paths and hashes, not contents. Exclusions are intentionally conservative but not an exhaustive secret detector. Included directory and file symlinks are rejected, and scan errors abort the report. Cross-tree file/directory ancestor collisions are conflicts. Reports are written through a temporary file and atomically replaced, so an existing hard link is not truncated. Scans are not atomic, so reports made while either stream is changing are provisional. Use stable snapshots and an output directory that is not being renamed or moved during the run; directory ancestry checks are point-in-time and do not defend against adversarial concurrent moves. A missing captured file in a selected scope is treated as deletion; inspect before acting. This tool never copies, deletes, merges, or writes either source tree.

## Safe integration procedure

1. When both streams stop writing, make read-only snapshots of each complete source tree, preserving copies of the baseline capture and manifest separately. Record final revisions and hashes; do not assume either active working directory is stable. Re-run the inventory against the snapshots and save the report outside them.
2. Create a separate integration candidate from the immutable baseline. For tracked files, review `git diff 975d674 <final-codex-commit> -- implementation` and the Claude snapshot against baseline. If a patch is useful, `git diff 975d674 <final-codex-commit> --binary -- implementation > codex-tracked.patch` captures only tracked Git content; inspect before applying it. A hash manifest is not a replacement for preserved baseline file contents. Compare captured untracked/ignored paths separately and bring first-party source and fixtures into the candidate deliberately. Check newly added ignored files in both snapshots too; a Git patch omits them.
3. Apply non-overlapping reviewed edits in the candidate. For conflicts, use three actual file versions (baseline, Codex, Claude) with `git merge-file` on candidate copies, then manually resolve and inspect each result, including delete/edit choices. Do not run merge-file on originals. Preserve both sets of relevant tests and avoid applying generated artifacts as authoritative source.
4. After source integration, regenerate OpenAPI and TypeScript contracts only if required, then run the contract drift checks, backend/worker/frontend suites, and targeted integration tests. Review security-sensitive behavior, dependencies and any generated diff. Document test results, unresolved conflicts, and external acceptance blockers before considering promotion.

At audit time, 212 of the manifest's 279 files were tracked; the other 67 were two `.DS_Store` files and 65 generated `backend/build/lib` copies. The package lock and three captured evaluation corpus JSON fixtures are tracked. This is a snapshot observation, not a guarantee for new files: review ignored first-party additions and fixtures before producing the final commit. Do not treat the generated build copies as the only surviving source without checking their authoritative counterparts.
