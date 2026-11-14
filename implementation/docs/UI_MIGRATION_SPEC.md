# Horizon to VIVA UI migration specification

Status: design analysis; implementation and visual acceptance pending. Reference extracted from `/Users/dhaanish/Downloads/horizon-main.zip` into `reference/horizon/horizon-main` after rejecting absolute paths, `..` components, and symlinks. The archive was not modified. This document describes the inspected source, not a claim of runtime verification.

## Design language

Horizon is an editorial, conversational learning product: warm ivory paper, deep plum navigation, coral calls to action, muted lavender and mint accents, large serif headings, a quiet sans-serif body and a monospaced code face. Source `app/globals.css` defines plum `#24152f`, plum-soft `#34203f`, plum-line `#4a3358`, coral `#ff735c`, coral-deep `#e85a43`, mint `#b9e4d0`, mint-deep `#6fb999`, ivory `#fff8ef`, ivory-deep `#f6ead9`, lavender `#8c78b8`, lavender-soft `#e6dff3`, ink `#29232d`, card `#fffdf9`, border `#eadfce`, muted text `#6b5f72`, and focus ring `#8c78b8`. Base radius is 14px; cards use rounded-3xl and low shadows, pills are fully rounded. Grain is an 18px radial dot texture. Heading stack Lora/Georgia, body Inter/system, code JetBrains Mono/monospace; supply reliable local/system fallbacks and do not make network fonts a dependency. Verify text and control contrast rather than assuming reference combinations pass.

Reference primitives in `components/ui-kit.tsx`: card, progress bar (bounded 0–100 and ARIA values), pill, page header, form field and primary/ghost/dark buttons. Shell: 256px sticky dark desktop sidebar; compact dark mobile header and fixed bottom navigation; max-width 72rem content; responsive card grids. Landing has split hero, mentor artwork, dark three-step section, path cards and reward section. Practice has search, chips and result rows. Arena presents problem, Monaco editor, mentor and stages. Adapt hierarchy and spacing in native CSS, retain React 18/Vite; do not import Next routing, Tailwind configuration, React 19 or bundled reference business logic.

## Preserve VIVA behavior

`src/App.tsx` owns real coordinator calls and guarded state transitions; `state/sessionLifecycle.ts`, `state/useSessionStore.ts`, `services/apiClient.ts`, `services/speechStreaming.ts` and audio services are behavior boundaries. Keep them and their revision, stale-response, session/token, interruption and reveal checks. `ProblemLibrary.tsx` must retain API-backed catalog, URL filters, bookmarks, spec-version links, draft and resume. `WorkbenchComponents.tsx` must retain domain acknowledgement, examples and constraints, save/version/dirtiness, typed and recorded explanation, user confirmation before execution and reveal, hidden diagnostics, bounded verification reports, trace, graduated evidence-grounded hints and held-out transfer checkpoint. Retain accessibility labels and keyboard semantics on all responsive panes. Never represent a bounded checkpoint as mastery or unavailable execution as success.

Horizon `lib/store.tsx` explicitly implements browser-local demo accounts/progress, `lib/arena.ts` and arena components implement demonstration behavior, and `hooks/use-speech.ts` uses browser speech synthesis. Do not transplant these, sample progress/reset, fabricated scores, rewards, fake login/password reset, hardcoded catalog or assumed provider capabilities. A profile, progress chart, paths or authentication page requires an existing truthful source and working action before becoming active; otherwise omit the control or explicitly show unavailable status. Gnani integration remains VIVA's services with text fallback identified honestly.

## Implementation targets and sequencing

1. `src/style.css`: map design tokens, typography, focus, button/card/field/pill styles and responsive breakpoints; honor reduced motion. Scope changes to avoid editor styles leaking.
2. `src/components/WorkspaceChrome.tsx`: visually adapt desktop and mobile navigation, settings and tabs while retaining current callbacks, focus restoration, labels and navigation paths. Show only supported destinations.
3. `src/components/ProblemLibrary.tsx`: Horizon-style hero, search/filter chips and readable rows, bound to existing route/state and metadata. Preserve every filter and version/draft state, empty/loading/error and retry.
4. `src/components/WorkbenchComponents.tsx` and `src/components/PythonEditor.tsx`: render the real workflow using Horizon arena hierarchy and panel styling. Keep all actions and labels; no simulated stage machine. Preserve keyboard pane access and scrollable evidence on narrow screens.
5. `src/App.tsx`: change composition only as needed for shell and responsive layout, preserving handlers and guards. `src/state/productState.ts` only if supported navigation requires it; keep URL/history and persisted draft compatibility.
6. Add small presentational primitives/components only if used by real screens. `public/mentor/mentor.png` is reference artwork with unverified license/provenance; check reuse rights before copying. A CSS-only treatment or neutral text is an acceptable interim design, not evidence of rights.
7. Update component and journey tests where semantics or user-facing labels change; verify catalog/version, start/resume, editor saving, prediction confirmation/reveal, verification, trace/hints, transfer, text and speech/error states. Run typecheck, build, relevant Vitest and responsive keyboard/browser checks with backend availability and execution status explicitly recorded.

## Accessibility and acceptance

Preserve semantic landmarks, heading order, labelled fields, button names, focus visibility, dialog focus handling, tabs and keyboard controls. Ensure bottom nav cannot cover content, narrow viewport avoids horizontal clipping, controls meet target sizing, statuses are announced without repeated interruptions, and reduced motion disables decorative animation. Test 320px/mobile, tablet and desktop; inspect loading, empty, offline, service unavailable and long-content states. Compare actual screenshots with reference only after rendering both; static source analysis does not establish visual parity. Live execution and speech remain separate acceptance gates from mocked UI tests.

## Reference execution

`package.json` has plain `next dev`, but dependencies and Next configuration have not been installed or independently security-reviewed; no Horizon server or screenshots were run/captured in this analysis. Runtime visuals therefore remain pending. Never point this reference at VIVA's dependencies or occupied service ports.
