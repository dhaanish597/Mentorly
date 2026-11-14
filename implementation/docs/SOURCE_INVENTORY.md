# Source inventory — local takeover

Updated: 2026-11-14. One active tree: `/Users/dhaanish/Desktop/VIVA/implementation`.

## Current local candidate (2026-11-14)

The expanded local application is separate from the historical import identities below. Current verification and source-only checkpoint evidence live in `../../evidence/workspace-expansion-20261114/`; consult `IMPLEMENTATION_STATUS.md` for measured checks and unresolved acceptance. The checkpoint manifest, not a prior Gemini/Drive filename or historical test count, binds the current source bytes. No Drive synchronization, source publication, push, or promotion was performed.

## Authoritative locations

| Source | Drive ID | Role |
|---|---|---|
| Main root | `1jWMkdgMfBaTanpQHekR_o9WlxC-lv97D` | Canonical publishing destination |
| Main implementation | `1mmsMOQQ-mbRhmEUawG-AnQs_4NwQZYy5` | Canonical logical source paths |
| Secondary root | `180tEut_BJOupH4fFUdQMlQ07u1q6a_wq` | Continuation overlays/history |
| Corrected plan v2.0.0 | `1EZkHCtkDyMNXw_i8-MoMPSHfZYFYnl4E` | Authoritative phase/product definitions |
| Gemini canonical manifest | `1V1QbCveVYAbn6oVfmpmBsth3ZMWrCi_-` | Original explicit overlay mappings |
| Reconciliation bundle | `1mRQch2vyqGuNzgjaf1_imMFJKvAcHkJ0` | Additional P3–P9 mappings |

The local plan is 135,956 bytes; recomputed SHA-256:
`67046fe8c5caaee4a863d4e17a1fdfb5915d741fd2175877730f214ce74a7f74`.

## Preserved import and reconciliation evidence

Original import directory: `imports/drive-20261113` relative to the VIVA root, not inside the active application. Its `inventory.json` contains 356 Drive entries; `downloads.json` contains 278 downloads (141 main, 137 secondary), with IDs, logical paths, MIME types, modification times, SHA-256, actual MD5, byte counts and export flags. All 278 raw SHA-256 checks passed in this takeover; none was missing. Nineteen entries are recorded in `excluded.json`.

`resolved_source_map.json` selects 129 original destinations with 29 explicit overlays. The assembly code corrected the bundle's one-character file-ID typo by matching the actual inventoried raw file. Size-claim discrepancy list is empty. These facts establish preserved-byte integrity, not current Drive freshness or application completion.

Codex had already modified numerous selected files and added integration work before this takeover. Those local differences were preserved, not overwritten by reassembly. The current manifest records origin IDs separately from current content hashes.

## Native export gap — BLOCKED_EXTERNAL

Five native Google Docs were marked exported but downloaded as **zero bytes**. Their contents were not verified:

| Logical record | Drive ID |
|---|---|
| PHASE_2_REPAIR_STATUS.md | `1IUW49Wo8ziarEqmM8w1g8fKoa_Y90TEWx5y0q0WDmVg` |
| CODEX_TAKEOVER_AUDIT.md | `1jP1tw_7DJRZ9lJusnCN6UI83Dk4mq6qlNdUxBhH6jnU` |
| ACCOUNT_HANDOFF.md | `1hPo4dj7T4EZJtWecHrwR4f2x97hfMRtKxNeHW1M007k` |
| ACTIVE_WORK.md | `1PkoUOG4gHu3bPmduZygeS9oCa0x8bLeMhgpLKtQFqcI` |
| DRIVE_RECONCILIATION.md | `1ipdBfMZEdvsRCeBYh4SkgzOKgFbqh9WvkkT9y0WlAEg` |

Local replacements are new takeover reports, not reconstructions of those unseen documents. A proper authenticated text export remains necessary. No Drive connector was available in this session; browser login does not establish connector edit permission. No new download, remote capability verification, upload, sharing change or promotion is claimed.
