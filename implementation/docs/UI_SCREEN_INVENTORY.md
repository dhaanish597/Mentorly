# Horizon reference and VIVA screen inventory

Source-level inventory; visual/runtime validation pending. Routes refer to Horizon Next files; VIVA currently uses its own URL/history state, not Next routing.

| Reference screen | Reference source | Visual/interaction pattern | VIVA adaptation and truth boundary |
|---|---|---|---|
| Landing `/` | `app/page.tsx` | split editorial hero, mentor illustration, CTA, three steps, paths, rewards | Adapt as an entry only if its links lead to real VIVA flows; use actual workflow and catalog, avoid demo claims/XP. |
| Auth `/auth/login`, `/auth/sign-up`, `/auth/forgot-password`, `/auth/reset-password` | `app/auth/*/page.tsx`, `components/auth/auth-shell.tsx` | centered branded forms | Reference localStorage demo accounts are not authentication. No active account actions without real supported backend. |
| Home `/home` | `app/(app)/home/page.tsx`, `components/dashboard/widgets.tsx` | dark resume hero, metrics, paths, recent activity, badges | Derive resume and draft only from VIVA state; no invented streak, badge, XP or activity. |
| Practice `/practice` | `app/(app)/practice/page.tsx` | searchable/filterable list, difficulty/path chips, empty state | `ProblemLibrary.tsx`: preserve metadata, versions, query, bookmarks, progress, drafts and resume. |
| Arena `/practice/[challengeId]` | `components/arena/{arena,problem-panel,code-panel,mentor-panel,stage-panels,result-dialog}.tsx` | multi-panel problem/editor/mentor, staged dialog and result | `App.tsx`, `WorkbenchComponents.tsx`, `PythonEditor.tsx`: preserve real session and evidence flow, confirmation/reveal and failure states; no reference grading. |
| Paths `/paths` and `/paths/[pathId]` | `app/(app)/paths/**`, `components/dashboard/path-detail.tsx` | path cards, grouped levels and progress | Render only if mapped to real VIVA collections and genuine progress; no fabricated unlocks. |
| Progress `/progress` | `app/(app)/progress/page.tsx`, `lib/gamification.ts` | cards, charts, activity grid, badges | No sample data or unsupported aggregate metrics; use truthful existing status or omit. |
| Profile `/profile` | `app/(app)/profile/page.tsx` | account and speech preferences, switches, destructive reset | VIVA settings remain backed by actual voice preferences and diagnostics. Do not adopt local demo identity/password controls. |
| Global shell | `components/app-shell.tsx`, `components/ui-kit.tsx`, `components/brand-logo.tsx` | dark desktop sidebar, mobile header/bottom nav, cards/pills | Adapt `WorkspaceChrome.tsx`; preserve route callbacks, accessible tabs and settings dialog. |
| Mentor | `components/mentor/doodle-mentor.tsx`, `public/mentor/mentor.png` | illustration, expressive animation | Reference asset rights unverified; preserve real coach text/audio and reduced-motion behavior. |

VIVA workbench also has states absent from the reference that must remain visible: unavailable coordinator or execution, spec change acknowledgement, unsaved code superseding prior evidence, microphone and streaming errors, editable transcript confirmation, hidden diagnostic prediction, bounded verification report and termination, trace navigation, stale hint suppression, repair and held-out transfer checkpoint. Responsive layouts must expose these states and controls without relying on color alone.
