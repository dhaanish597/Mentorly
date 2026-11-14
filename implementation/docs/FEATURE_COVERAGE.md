# Approved feature coverage / complete requirement traceability

**Last updated:**2026-11-14. **Overall IN_PROGRESS,not complete.** Authority:`/Users/dhaanish/Desktop/VIVA/IMPLEMENTATION_PLAN.md` v2.0.0 §§1.5–1.6,12.2–12.3 plus explicit user exercise/UI/voice expansion. All **FR-01–22/NFR-01–07** remain required; runtime-selectable WS/model paths are not removed scope.

VERIFIED_LOCAL means only stated local/protocol subset. IMPLEMENTED_UNVERIFIED means implemented but full acceptance open. BLOCKED_EXTERNAL/BLOCKED_TOOL/PENDING are never passes. Owners denote module responsibility,not invented human contributions. Paths below are relative to `/Users/dhaanish/Desktop/VIVA/implementation`.

## Evidence / owner / test keys

- **E1 final local suite:**workspace `evidence/workspace-expansion-20261114/final-checkpoint-checks/{full_check_results.json,check_results.json,TEST_LOGS.txt}`: **503 backend PASS,207 worker PASS,120 frontend PASS,9 genuine gVisor/trace/execution SKIPS;17 checks PASS,0 FAIL,4 omitted/external markers**. Typecheck/build/drift/secrets/archive pass. Named subsets overlap totals. Credential-free/omitted-live markers deliberate; isolation/code evaluation genuinely blocked.
- **E2 provider:**workspace `evidence/expanded-coach-20261114/gnani-provider-aggregate.json`, `gnani-tanglish-synthetic-batch2.json` and `evidence/workspace-expansion-20261114/browser-voice.json`. Final **11 authorized calls,373 TTS chars,27.76 STT seconds;+2 unintended dummy401 tests=13 attempts**,correctedMockTransport. Protocol/synthetic/software evidence,not human accuracy.
- **E3 browser:**workspace-expansion before/light/dark/mobile screenshots/geometry,including `before-1366x768.jpg`,`before-layout.json`,`after-workspace-1366x768.jpg`,`after-workspace-1440x900.jpg`,`after-workspace-dark-1366x768.jpg`,`after-mobile-375.jpg`; actual hidden-confirmation/unavailable/restore/dirty-draft journey. **Observations predate final cache/guard/Replay/toolchain patches; final runtime refresh BLOCKED_TOOL.**
- **E4 evaluation:**`evaluation/README.md`,`evaluation/validate_readiness.py`,`evaluation/run_code_eval.py`,`evaluation/speech_ablation/audio_manifest.json` and original corpora.24 slots0 recordings/4 speaker slots0 consent;6–8 classmates needed;no accepted runsc code report.
- **E5 coverage/audit/wheel:**workspace-expansion `verified-coverage.json`,`frontend-coverage-verified/coverage-summary.json`,`npm-audit-final.json`,`wheel-final-build.log`,`wheel-final/vcc_coordinator-0.1.0-py3-none-any.whl`; parent-verified isolated installed-wheel HTTP catalog31 with explicit externalbranding/no repo module fallback/provider0/learner0.

| Owner key | Actual modules |
|---|---|
| CAT catalog | `backend/app/exercises/{registry,catalog_data,legacy_data,catalog_validator,values,oracles}.py` |
| CORE config/contracts | `config/branding.json`,`backend/app/core/{branding,config,execution_readiness}.py`,`backend/app/models/{domain,api_schemas,enums}.py` |
| API/persistence | `backend/app/api/{routes_meta,routes_sessions,session_security}.py`,`backend/app/db/repository.py`,versioned migrations |
| LIFE orchestration | `backend/app/orchestration/{state_machine,restore,worker_client}.py` |
| SPEECH | `backend/app/speech/{gnani_adapter,service,routes,ws_streamer,gatekeeper,audio_utils,ast_keyterms,transcript_normalizer,pre_tts_normalizer,tts_cache}.py` |
| COACH | `backend/app/coaching/{claim_extractor,coach_engine,templates,prompt_guard}.py` |
| WORKER/verification | `exec_worker/worker_app/{sandbox_runner,verifier_harness,trace_recorder}.py`,`exec_worker/runner/{in_sandbox_tracer,safe_serializer}.py`,`backend/app/verification/{hypothesis_strategies,minimizer}.py` |
| OPS | `backend/app/operations/{admission,retention,readiness,backup}.py` |
| UI | `frontend/src/App.tsx`,`frontend/src/components/{ProblemLibrary,WorkspaceChrome,WorkbenchComponents,PythonEditor}.tsx`,`frontend/src/state/{productState,useSessionStore,sessionLifecycle}.ts`,`frontend/src/services/{apiClient,audioRecorder,audioPlayer,speechStreaming}.ts` |
| EVAL/package | `evaluation/{validate_readiness,run_code_eval}.py`,`evaluation/speech_ablation/run_speech_ablation.py`,`scripts/{start_local,run_all_checks,check_schema_drift}.py`,Dockerfiles/Compose/deployment runbook |

Tests (under implementation):

- **T-C:**`backend/tests/unit/test_expanded_catalog.py`,`test_catalog_execution.py`,`test_exercises_oracles.py`,`test_contracts.py`;`backend/tests/integration/test_catalog_contract.py`.
- **T-L:**`backend/tests/integration/test_learning_lifecycle.py`,`test_http_journey.py`,`test_p3_to_p7_integration.py`;`backend/tests/unit/test_atomic_revision_publication.py`,`test_db_migrations.py`,`test_r1_to_r9_regressions.py`.
- **T-W:**`exec_worker/tests/test_broker_and_verifier.py`,`test_hypothesis_budgets.py`,`test_hypothesis_provenance.py`,`test_verifier_shrinking.py`,`test_runner_protocol_and_trace.py`,`test_serializer_identity.py`,`test_sandbox_isolation.py`,`test_deployment_packaging.py`.
- **T-S:**backend speech foundation/takeover/configuration/dispatch-freshness/cache-admission/provider/tanglish/model-configuration-boundary unit tests;`backend/tests/integration/test_voice_introduction.py`. Final stale HTTP speech-replay guard:28 tests/narrow review; public-cache/replay/auth/lifecycle regressions included in recorded suites.
- **T-O:**`backend/tests/integration/test_admission_limits.py`,`test_retention_and_backups.py`;unit evaluation-readiness/check-runner/local-startup tests.
- **T-F:**`frontend/src/__tests__/App.test.tsx`,`workbench.test.tsx`,`productComponents.test.tsx`,`productState.test.ts`,`coachActions.test.tsx`,`lifecycle.test.tsx`,`sessionLifecycle.test.ts`,`typedPrediction.test.ts`,`audioServices.test.ts`,`speechStreaming.test.ts`,`voicePreferences.test.ts`,`voiceStreamingPreferences.test.ts`,`apiClient.test.ts`;final Replay/acceptance additions included in120-test suite.

## Complete functional requirement matrix

| ID / requirement | Owner / module key | Tests | Evidence | Status / outstanding acceptance |
|---|---|---|---|---|
| FR-01 Configurable branding | CORE+API+UI | T-C,T-F;meta tests | E1,E5 | VERIFIED_LOCAL branding/meta/render/wheel config subset; final brand undecided/deployment unverified |
| FR-02 Exercise/spec selection | CAT+UI | T-C,T-F | E1,E3,E5 | VERIFIED_LOCAL31 problems32 specs,original IDs preserved; all31 accepted runtime behavior pending |
| FR-03 Code versioning/AST bias | API+LIFE+SPEECH+UI | T-L,T-S,T-F | E1 | VERIFIED_LOCAL monotonic versions/hash/CAS/save/stale/AST subset; <=50ms broader-device performance not certified |
| FR-04 Context-biased Gnani STT | SPEECH+UI capture | T-S,T-F | E1,E2 | IMPLEMENTED_UNVERIFIED overall; genuine REST/codemix passed,human accuracy/device/allcatalog matrix pending |
| FR-05 Critical tokens/confirmation | COACH+CORE+UI | T-C,T-L,T-S,T-F | E1,E3 | VERIFIED_LOCAL strict typed chips/explicit gate; browser hidden-until-click observed before final patches; latest-runtime spoken journey pending |
| FR-06 Sandbox/bounded search | WORKER+LIFE | T-W,T-L | E1,E4 | IMPLEMENTED_UNVERIFIED/BLOCKED_EXTERNAL,no dedicated authorizedLinux/runsc; generated/protocol cases not execution proof |
| FR-07 Bounded attributed trace | WORKER+UI | T-W,T-F | E1 | IMPLEMENTED_UNVERIFIED250-event/safe protocol subset; real frame/source/post-line accuracy and browser trace blocked |
| FR-08 Prediction-before-reveal | LIFE+API+UI | T-L,T-C,T-F | E1,E3 | VERIFIED_LOCAL hidden challenge/full revision/confirmed output/redaction; actual boolean unavailable journey,no accepted comparison run |
| FR-09 Independent code/prediction | CORE+LIFE+COACH+UI | T-L,T-C,T-F | E1,E3 | VERIFIED_LOCAL independent MATCH/MISMATCH/NOT_EVALUATED/code-status/unsupported abstention; zero-case unavailable has no success badge |
| FR-10 Three graduated hints | COACH+LIFE+UI | T-L,T-S,T-F | E1 | IMPLEMENTED_UNVERIFIED sequentialL1/L2/L3/evidence gates; real trace-pointer grounding pending,no solution dump |
| FR-11 Technical TTS/cache/stop | SPEECH+UI audio | T-S,T-F | E1,E2 | IMPLEMENTED_UNVERIFIED normalization/SSE/WAV/software stop; physical audible<=150ms and NFR medians unverified |
| FR-12 Domain shift/fresh transfer | CAT+LIFE+UI | T-C,T-L,T-W,T-F | E1 | IMPLEMENTED_UNVERIFIED domain ack/prior failure/disjoint/exhaustion/initially-correct logic tested; actual accepted repair/transfer blocked |
| FR-13 Freshness/cancel/playback ack | LIFE+SPEECH+API+UI | T-L,T-S,T-W,T-F;28speechguard tests | E1,E2 | VERIFIED_LOCAL revision/capture/CAS/staleHTTP-replay/late-ack gates; per-messageReplay final2bounds/error-eviction fixes pending validation; runtime refreshBLOCKED_TOOL |
| FR-14 Typed fallback/queue/demo | SPEECH+API+OPS+UI | T-L,T-S,T-O,T-F | E1,E3 | IMPLEMENTED_UNVERIFIED typed/queue/retry/cache provenance; no accepted sandbox demo or deployed capacity claim |
| FR-15 Restore/summary/export/delete | API+LIFE+OPS+UI | T-L,T-O,T-F | E1,E3 | VERIFIED_LOCAL auth/revision/hidden-redaction/tombstone/draft-resume subset; final patched-runtime/deployed acceptance pending |
| FR-16 REST/WS/SSE/WAV/endpointing | SPEECH+UI services | T-S,T-F | E1,E2 | IMPLEMENTED_UNVERIFIED genuine transport protocols,both languages selectable; all exercise/language/device permutations/endpointing pending,no full duplex |
| FR-17 Model/deterministic modes | COACH+CORE | T-S,T-L | E1 | IMPLEMENTED_UNVERIFIED live model; constrained model/mock/fallback tested; Groqkey/modelmissing,no Groqcall. Standardenv provider=groq,not QA-forced deterministic |
| FR-18 Admission/budgets/evaluator/cache | OPS+SPEECH+API | T-O,T-S | E1,E2 | IMPLEMENTED_UNVERIFIED durable caps/uncertainty/public-generic vs personalizedcache/privacy tested; deployed capacity/evaluator arrangements/tariff unknown |
| FR-19 All13views/responsive/a11y | UI | T-F | E1,E3 | IMPLEMENTED_UNVERIFIED compact/mobile/theme/reducedmotion/progressive controls; fullWCAG/browser/hardware matrix and final-source refresh pending; chunkwarning |
| FR-20 Dataset/code/speech/user evaluation | EVAL+WORKER | T-O,T-W | E1,E4,E5 | BLOCKED_EXTERNAL accepted code report/human24clips4speakers/6–8classmates absent; statementcoverage met,branch/function below80; synthetic ablation nothumanbenchmark |
| FR-21 Immutable challenge/spec/CAS/reveal | CORE+API+LIFE+UI | T-C,T-L,T-F | E1,E3 | VERIFIED_LOCAL immutable hashes/domainack/confirmation/redaction/CAS; accepted runtimeintegration open |
| FR-22 Deploy/rollback/repro/demo/submission | EVAL/package+OPS | T-W,T-O;build/drift/wheel | E1,E5 | IMPLEMENTED_UNVERIFIED:wheel/installHTTPcatalog passes,finalnpm audit0snapshot; host/images/TLS/deployedrollback/demo/finalruntime acceptance pending; nopublicationauthorized |

## Complete nonfunctional requirement matrix

| ID / target | Owner / module key | Tests | Evidence | Status / measurement boundary |
|---|---|---|---|---|
| NFR-01 Medians<=1.8s interpretation/<=1.2s evidence/<=2.2s firstaudio | SPEECH+CORE+UI+EVAL | T-S,T-F;offlineAST/ablation | E1,E2 single samples | UNVERIFIED targetmedians; timed-debug stop/one synthetic turn not benchmark or guaranteed foreground latency |
| NFR-02 Measured per-invocation isolation | WORKER+CORE+operator | T-W realtests skipped | E1,E4 | BLOCKED_EXTERNAL dedicatedhost/image/daemon/resource/adversarial/cleanup proof absent; executionoff,no weakerfallback |
| NFR-03 0% stale feedback in races | LIFE+API+SPEECH+UI | T-L,T-S,T-F;HTTPguard | E1 | VERIFIED_LOCAL CAS/capture/dirty/replay freshness subset; final2Replaybounds/error fixes pending,final-runtime stress/browser refresh blocked |
| NFR-04 Costcaps/reservations/cache/unknownbalance | SPEECH+API+OPS | T-S,T-O | E1,E2 | VERIFIED_LOCAL atomic call/STTsec/TTSchar budgets/uncertainty/publiccache replay; exact usage disclosed,tariff/credit/production capacity unknown |
| NFR-05 Consent/24hretention/delete | OPS+API+SPEECH+EVAL | T-O,T-L,T-S | E1,E4 | IMPLEMENTED_UNVERIFIED localcleanup/private/publiccache separation; actualhumanconsent0,provider/backups outside localdeletion guarantee,nolegalcertification |
| NFR-06 Keyboard/captions/ARIA/contrast | UI | T-F | E1,E3 | IMPLEMENTED_UNVERIFIED semantics/captions/tabs/theme/reducedmotion subset; fullshortcuts/screenreader/WCAG/browser/device matrix pending |
| NFR-07 Auditable self-contained artifacts | CORE+API+WORKER+EVAL | T-C,T-L,T-W,T-O;drift | E1,E2,E4 | VERIFIED_LOCAL typed/fullrevision/hash/seed/version/timings/provenance; actualrunsc artifacts/traces absent,no fabricated outputs/provider identity |

## Expanded catalog / evidence boundary

31 distinct original problems32 specs,original `ex1_shortest_subarray` v1_positive_only/v2_negatives_allowed,`ex2_binary_search` v1_sorted_with_duplicates,`ex3_max_product` v1_bounded_ints preserved. Strictinteger/bool/string/flat scalar-list inputs/predictions/results reject coercion,bool/int alias,float/null/object/nested outputs. Generic173curated64transfer626generated31examples31knownbug31alternatives are data/oracle validation counts,not accepted executions. Original12-bug/atleast6-alternative evaluation corpus separate.

Final authored sources AST-only. Earlier120 ordinary-subprocess authored-fixture checks were stopped/removed,not isolation or accepted behavior. Protocol doubles do not execute learner code. Runtime acceptance across all31 remains pending.

## All13 authoritative views mapped to progressive app states

Common ownership UI modules/T-F/E1; panels can share appstates,not separate pages.

| Plan §2.2 view | Appstate(s)/panel | Acceptance boundary |
|---|---|---|
| 1 Entry/library/header | ONBOARDING_MIC_CHECK,EXERCISE_BRIEF_SPEC;ProblemLibrary/WorkspaceChrome |31problem search/filter/bookmark/resume/URL drafts; final-source refreshpending |
| 2 Constraints/language/domainack | EXERCISE_BRIEF_SPEC,DOMAIN_SHIFT_ACK_GATE | English/Tanglish/domainbanner/ack preserved |
| 3 Microphone/audio setup | ONBOARDING_MIC_CHECK;AudioWorklet/audio services | permission/RMS/typed paths;actualhumanmic/speakerunverified |
| 4 Editor/version/dirty | EXPLAIN_APPROACH_TURN and revision-sensitive states;PythonEditor | Monaco/CAS/dirty suppress stale results;final toolchain browser refreshpending |
| 5 Transcript/confirmation | TRANSCRIPT_CLAIM_CONFIRMATION | raw/normalized/strict values,explicitfocus/confirm,stickycard |
| 6 Hidden prediction | PREDICT_CHALLENGE_OUTPUT | immutable input/revision,hidden until click |
| 7 Execution comparison/progress | ISOLATED_VERIFICATION_PROGRESS→REVEALED_COMPARISON_VIEW | independent statuses,actualunavailablezero cases/no success;acceptedrunblocked |
| 8 Trace navigation | TRACE_SCRUBBER_INSPECTION | bounded/scrubberprotocol;actualrunscframe/line evidenceblocked |
| 9 Hints/audio/conversation | SOCRATIC_HINT_PROGRESSION | graduatedhints/per-messageReplay/testedlateack;last2cachefixvalidationpending |
| 10 Revision/retest | SOCRATIC_HINT_PROGRESSION,ISOLATED_VERIFICATION_PROGRESS | priorfailure/fullrevisionrepair/retry;actualsandboxrepairblocked |
| 11 Fresh transfer | FRESH_TRANSFER_CHALLENGE | unused/disjointcase/correctcode+prediction gate;actualcompletionblocked |
| 12 Summary/export | PRACTICE_CHECKPOINT_SUMMARY;Sessiontab | boundedfactualsummary/restore/export/delete redaction;nomastery |
| 13 Queue/errors/retry | QUEUE_DEGRADATION_RECOVERY;status/diagnostics/footer | fallback/cancel/retry/unavailable;44pxstickycontrols;capacityunverified |

All13 appstateIDs retained: onboarding,brief,domainack,explain,prediction,confirmation,progress,comparison,trace,hints,transfer,summary,recovery.1366×768 page768/editor432 and1440×900 page900;internalpanes after firstchoice,mobile375/682reflow/theme/reducedmotion observed. Existing5180/library uses earlier-loadedbackend; browserclassifieroutage prevents restart/viewportreset. Final-source refresh **BLOCKED_TOOL**,not full current acceptance. User must stop only owned8020/5180 previews or wait service recovery,then relaunch explicitproxy per ACCOUNT_HANDOFF.

## Language / transport / model matrix

| Mode | Implemented path | Evidence/status | Not established |
|---|---|---|---|
| English en-IN RESTSTT | WAV/contextbias/confirmation | E1/E2 genuineprotocol | humanaccuracy/all31devicecombinations |
| Tanglish ta-IN,en-IN RESTcodemix | raw+normalized editableproposal | E2 synthetic7/7programmingtokens/Tamilimperfection |24humanclipbenchmark |
| English/Tanglish WSSTT | authenticatedboundedPCM/commit/selectable | E1/E2 genuineWShandshake/transcript | bothlanguages×allcatalog liveobservation/endpointing/device/full-duplex |
| SSETTS/streamingPCM | incrementalprovider/audio relay | E1/E2 genuineprotocol | deployedfirstaudio/turnmedians/browsermatrix |
| WAV/public-generic/private/cacheReplay | scopedfetch/ack/messagekeys | E2 actual3.84sWebAudio,localreplayzeroTTS | physicalaudiblelatency/finalsourcebrowseracceptance |
| Deterministic coaching | grammar/templates/unsupportedabstention | E1 operational,previewcredentialfree | modelintelligence/Groqcall |
| Groq-assisted extraction/phrasing | strictschema/approvedtemplates/timeoutfallback | E1 mock/boundarytested,key/modelmissing | requiresprivate VCC_GROQ_API_KEY,VCC_LLM_MODEL,VCC_LLM_PROVIDER=groq standardstart,not QAforceddeterministic;livequalityunverified |

## Final coverage / dependency / packaging snapshot

| Metric | Final result | >=80% statement target |
|---|---|---|
| Python aggregate statements |81.4403149%,7034/8637 | Met |
| Frontend statements |81.05%,1703/2101 | Met |
| Frontend lines |88.53% | separate metric |
| Frontend branches |77.29% | below80 |
| Frontend functions |74.00% | below80 |

Earlier Python78.5573%(6763/8609),intermediate81.4613%(7013/8609),frontend82.42%/initialVitest4mapper measurements are superseded historical observations. Do not average mappers/rewrite snapshots or claim everymetric>=80. Coverage gained meaningful tests without exclusions/authoredfixtureexecution;9realrunscskips remain partialacceptance.

Node24.21,Vite6.4.6,Vitest+coverage4.1.12,Reactplugin4.7.0,DOMPurify3.4.17;React18/Monaco0.57 unchanged. Finalnpm audit0allseverity/emptyvulnerabilities supersedes12/4critical and10dev-only snapshots; snapshot notfutureguarantee. Typecheck120testsbuildPASS;wheelbuilt/isolatedinstalledHTTPcatalog31PASS explicitexternalbranding/norepositorymodulefallback/provider0/learner0. Monaco largechunkwarning remains. No unsupplied completed Python registry audit claim.

Publicgenericcache/serverowned scope/version/language/voice/model keys(two sessions1mockTTS),private deletion separation and staleHTTPspeech guard(28tests+narrowreview) verified. Per-messageReplay artifact/fullrev/hint/cache/lateack tested; **last2bounds/error-eviction fixes still finalizing at cutoff: validate/rerun ifsourcechanges**,do not relabel E1 as post-fix evidence.

Still IN_PROGRESS: dedicatedauthorizedLinuxhost absent,Dockerdaemonabsent,SSHsavedtargetsnone;modelkey/modelmissing;physicalmic/speaker/human24recordings4consents/6–8study absent;finalruntime refreshBLOCKED_TOOL;fullWCAG/browser/latency/deployedcapacity/evaluator/TLS/rollback open. Same-modelreviews notCodexaudit. Localonly,noDrivepublication/gitcommit/push/publicpublish/paidprovision/submission;no secrets/DB/audio in docs/sourcecheckpoint. Parentowns expected future checkpointmanifest,notcreatedbythisdocpass. [Status](IMPLEMENTATION_STATUS.md),[decisions](DECISIONS.md),[handoff](ACCOUNT_HANDOFF.md),[capabilities](GNANI_CAPABILITIES.md),[operations](OPERATIONS.md),[deployment](DEPLOYMENT.md).
