# Drive reconciliation

Status: `IN_PROGRESS`; remote freshness and publishing: `BLOCKED_EXTERNAL`.

## Selected baseline

The existing Codex import was retained and checked locally instead of repeatedly downloading unchanged trees. All 278 saved raw SHA-256 checks passed. The corrected root plan matched its canonical recorded hash. The saved `imports/drive-20261113/resolved_source_map.json` remains the original explicit file-ID-to-destination resolution; the active application contains subsequent preserved Codex and takeover changes.

Sources selected by that map: canonical main base, `repaired_v2_p2` overlays, explicit unique `p3_to_p9_complete` bundle entries, and necessary unique historical configuration. Historical folders remain evidence, not additional active applications. No files were concatenated or selected solely by timestamp.

## Limits

Five Google Docs exports are empty; see SOURCE_INVENTORY.md. Their alleged newest handoff findings cannot be reconciled by ID alone. The existing R1–R9 regression identifiers are retained; new takeover defects use `LOCAL-*` identifiers in CODEX_TAKEOVER_AUDIT.md. A historical alias must be added only after comparing defect, affected code and reproduction in the missing documents.

Current Drive read/edit capabilities and concurrent Gemini changes could not be checked because no authenticated connector was exposed. The main implementation and previous canonical version have not been modified remotely.

## Candidate promotion protocol

1. Read both root capabilities and correctly export the five native documents.
2. Inventory current destination IDs/checksums and compare with the preserved import/checkpoint manifest. Stop on unexplained concurrent edits.
3. Create a versioned candidate source snapshot and promotion manifest; retain the old canonical identity.
4. Upload source to the main implementation's mapped logical paths, not loose files across roots. Exclude secrets, dependencies, caches, databases/sidecars and private recordings.
5. Upload reports and checksum manifests under one phase/run artifact directory. Use the secondary root only for a continuation pointer/handoff.
6. Read back every required file and compare raw content hashes. Record each non-atomic write and any incomplete upload.
7. Mark current only after acceptance and read-back gates pass. Partial or externally blocked candidates never replace a verified release.

This takeover leaves a **local candidate**, not a promoted Drive release. Exact candidate file hashes and archive checksum are recorded in the accompanying local promotion artifact.
