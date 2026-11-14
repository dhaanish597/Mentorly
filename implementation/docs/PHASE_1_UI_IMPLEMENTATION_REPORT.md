# Phase 1 UI implementation report

Status: local implementation and targeted acceptance checks completed; external execution, provider, broader accessibility and human review gates remain open. This report is a working checkpoint, not a claim of production readiness or complete Phase 1 acceptance. Git revision: see current isolated checkout HEAD and uncommitted changes (`git status`); changes are not committed at time of writing.

## Implementation

Horizon-inspired ivory/plum/coral tokens, typography and responsive layouts were applied to the Vite frontend. Added landing, dashboard, learning-path collection details, local practice-data progress, navigation and unknown-route handling in `src/ProductApp.tsx`. Existing library, domain specification, editor, session, coach and evidence components remain connected to the coordinator. VIVA branding is configured in `config/branding.json`. Settings uses the existing workspace dialog. Legacy tab-session recovery is explicit from the landing page; successful migration moves the credential to existing scoped tab storage. New sessions use scoped storage. No demo authentication, simulated grading or fake progress metrics were introduced.

Updated `src/main.tsx`, `src/App.tsx`, `src/components/WorkspaceChrome.tsx`, `src/style.css`, and added `src/__tests__/ProductApp.test.tsx`. Existing state/services/voice modules were retained. Horizon asset rights are unverified and its mentor asset was not copied.

## Local checks

- `NODE_OPTIONS=--no-experimental-webstorage npm run build`: passed (TypeScript and Vite; Monaco chunk-size warning remains).
- `NODE_OPTIONS=--no-experimental-webstorage npm test`: 14 files, 98 tests passed. Existing React `act` warnings remain. Node 26 requires the flag for the test environment; default invocation has baseline localStorage incompatibility.
- Coordinator test baseline reported by integration coordinator: 499 passed; worker 207 passed and 9 runsc-dependent skips. These are baseline results, not rerun by this UI workstream after every edit.
- Browser against isolated Vite :5290 and coordinator :8090: landing, dashboard, paths, progress, library, settings and workbench rendered; real 31-problem catalog and collection links observed. Desktop and mobile screenshots in `docs/screenshots/`. Browser resize requested 390px but tool reported a 500 CSS-pixel viewport; a true 390px check remains pending. At 500 CSS pixels, document width equaled viewport for landing, dashboard, paths, progress, library and workbench. First Tab focused the visible skip link. No console errors were observed on the inspected workbench. This is targeted keyboard/overflow coverage, not a complete accessibility audit.
- Browser practice journey: selected text mode, started a session, issued an input, proposed and confirmed a prediction. Coordinator returned `EXECUTION_UNAVAILABLE`; UI described the prediction as not evaluated and the worker as unavailable. Monaco loaded, accessible editor toggle worked, an edit showed unsaved/superseded evidence, save advanced code version from 1 to 2, and refresh restored version 2. The tested coordinator had custom execution disabled/unavailable; this is not real execution verification.
- Direct URL navigation, collection detail and invalid-route UI were implemented; automated tests cover entry, local counts, offline state, popstate, saved theme and legacy recovery. Full route/back and every problem journey remain to be independently exercised.

## Open gates

Linux/gVisor isolation acceptance and live execution remain externally blocked; do not enable custom code execution on this evidence. Live Gnani authentication/audio, human review, comprehensive WCAG and assistive-technology checks, true 320/390px browser checks, and a complete end-to-end regression across all DSA exercises remain outstanding. Screenshots are real local renders, not proof of those gates. Recent and saved items reflect device-local records; charts and gamification are intentionally absent without a truthful data source. The new screens' branding uses configured fallback while the workbench also consumes server branding; reconcile dynamic branding across surfaces if runtime branding changes are required.

## Coordinator local gate — accepted for safe Phase 2 integration

After the final UI fixes, backend + worker regression rerun: **706 passed / 9 externally blocked runsc skips** (499 backend +207 worker), 13.99 seconds. The only branding-dependent assertions were deliberately updated from the previous placeholder name to configured VIVA identity; custom branding override tests remain intact. Frontend98pass and production build passed.

Independent Playwright/Chrome checks at **actual390×844 and320×844** covered landing/dashboard/paths/progress/library/workbench/404. All14 page-width checks had scrollWidth equal viewport, with zero page errors. Raw results and390px screenshots: `coordination/evidence/phase1/responsive.json` and sibling PNG files. These narrow-screen checks supersede the500px tool limit above. Targeted keyboard, genuine edit/save/restore and unavailable-worker error behavior were observed; they do not establish full screen-reader/WCAG certification or real isolated execution.

The local Phase1 compatibility gate is accepted: no mandatory local regression remains, original capabilities and fail-closed execution boundary are preserved, and Phase2 can integrate safely. External Linux/runsc execution, real provider and human/device gates remain **externally blocked/unverified**, never passed. All-exercise registry/oracle contracts are tested; every exercise has not been executed through a real gVisor browser journey.
