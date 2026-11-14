# Architectural & engineering decisions

**Last updated:**2026-11-14. **Overall IN_PROGRESS**; engineering decisions/local test evidence are not blanket release acceptance.

Authority:`/Users/dhaanish/Desktop/VIVA/IMPLEMENTATION_PLAN.md` v2.0.0,historical Drive identity `1EZkHCtkDyMNXw_i8-MoMPSHfZYFYnl4E`,plus explicit user expansion. All FR-01–22/NFR-01–07 remain required.

## Consolidated expanded-scope decisions

- One active local app; preserve original imports/Codex/takeover deltas and originalR1–R9/exercise/spec IDs. No invented aliases to inaccessible zero-byte native exports. Drive is historical import/checkpoint surface,not live filesystem; current continuation localonly.
- User explicitly expanded exercise/UI/voice scope: **31 distinct original problems/32 specs**,originalthree/fourspec minimum retained. Scope changes belong here,no new top-level planning or continuation prompt.
- Strictinteger/boolean/string/flat scalar-list predictions/results throughout schemas/API/DB/worker/compare/restore/coaching/transfer;no coercion,bool/int equalityalias,float/object/nested outputs. Immutable challenge/fullrevision/CAS/hidden-answer/explicitconfirmation/independentstatuses unchanged.
- Generic173curated64transfer626generated31examples31bug31alternative counts describe localdata/oraclevalidation,not accepted sourceexecutions. Original12bug/atleast6alternative evaluation corpus remains separate required denominator. Final sourcefixtures AST-only inertstrings. **Earlier120 ordinary-host-subprocess authored-fixture checks were stopped/removed;not gVisor proof or accepted behavioral success.** No history claim that source never ran;no counting those checks as runtimeacceptance or executing fixtures to inflatecoverage.
- Actual no-network Linux/runsc acceptance mandatory,identity-bound to image/runtime/bundle/daemon;flags/markers/protocoldoubles notproof. No localDockerdaemon/no savedSSHtarget/no authorizedhost;executiondisabled,no hostPython/ordinaryDocker/AST-filter/RestrictedPython fallback. Trusted oracles remain outside sandbox;finite tests never prove mastery/universalcorrectness.
- Compactprogressive31library/search/filter/bookmark/resume/URLdrafts/internalpanes/mobiletabs/theme/reducedmotion preserves all13states. Stickyconfirmation/mic/stop and44pxfooter retained. Browser evidence/layout is separated from latest-runtime refresh,fullWCAG/browser/hardwarecertification.
- Standardlocalstartup explicitly chooses preview or privateenvfile. Fileauthoritative canonicalcredentials beat ambientwrongaccount/aliases;blank/placeholdercanonical blocksfallback. `.env` preservedbytes0600,neverprinted/copied todocs/source/archives/CLI/frontend. Groqkey/model missing; standardmodelpath requires VCC_GROQ_API_KEY,VCC_LLM_MODEL,VCC_LLM_PROVIDER=groq. LiveQAforceddeterministic is not modelacceptance;currentfallbackhonest/noGroqcall.

## Speech economy / replay freshness decisions

- Server-owned generic intro/test audio may use cross-session **public-byte** cache keys(scope/version/language/voice/model). No caller-controlled/personalized text enters public cache. Two sessions/one mocked synthesis proven. Personalized entries stay session-scoped;private deletion preserves onlypublicbytes. Publiccache never weakens confirmedchallenge/reveal authorization.
- Durable HTTP speech-idempotency replay checks current revision before audio bytes;samekey/body aftercodechange409/zerosynthesis.28tests+narrowreview verifyguard. Confirmed-ID cancellation deltas,durableuncertainreservations/cachebounds remain.
- Per-message Replay keyed artifact/fullrevision/hint;cachedreplayzeroTTS;lateacks cannotadvanceolderhint/currentmessage. **Last2replay-cache bounds/error-eviction fixes were still being finalized at summarycutoff.** Validate/rerun if sourcechanges;don'tclaim recordedfinalsuite contains unrecordedsubsequentfixes.
- Exactprovider accounting:initial8authorizedcalls189chars19.36sSTT;+2 unintendeddummy-key401REDtests stopped/fixedMockTransport(initialtotal10attempts). Separatelyauthorized3calls=syntheticTanglishTTS+STT2(122chars8.4sSTT)+browserTestVoice1(62chars). Final **11authorizedcalls373TTSchars27.76STTseconds,+dummy2=13totalattempts**. Localreplayzero additionalcalls. Workstopped,no open-endedproviderapproval.
- SyntheticactualTamil-English7/7rawprogrammingtokens,Tamilimperfection;not humanbenchmark. RealbrowserWebAudio3.84s/clockadvance/completion/timeddebugstop1.1ms-source6.7ms-ended usefulsoftwareevidence,not NFRbenchmark/physicalaudiblelatency/foregroundguarantee. Nohumanmic/speakercheck/study.24clipslots0recordings,4speakerslots0consent,6–8classmates needed;privatevalidator/freeze beforeheldoutmeasurement.

## Final local validation / dependency decisions

- Recordedfinal-checkpoint-checks: **503backend207worker120frontend PASS,9 genuinegVisor/trace/executionSKIPS;17checksPASS0FAIL4omitted/externalmarkers**. Offlinecredentialfree/omittedlive markers deliberate;genuineprovider elsewherepassed;realisolation/codeeval blocked. Subsettestcounts overlap.
- FinalPythonstatementcoverage **81.4403149%,7034/8637**. Frontend **81.05%statements1703/2101,88.53%lines,77.29%branches,74.00%functions**. Statementminimum metboth,notallmetrics. EarlierPython78.5573%(6763/8609),intermediate81.4613%(7013/8609),frontend82.42%/firstVitest4mapper are supersededhistoricalmeasurements,notaveraged/relabelledcurrent. Meaningful tests,no moduleexclusions/authoredsourcefixtureexecution;missingrunsc acceptance remains partial.
- Finaltoolchain Node24.21,Vite6.4.6,Vitest/coverage4.1.12,Reactplugin4.7.0,DOMPurify3.4.17;React18/Monaco0.57unchanged. ScopedMonacoDOMPurifyoverride installed,compatibledevtoolchanges reviewed;no forcedmajortransitiveoverride. EarlierconditionalXSS/noidentifiedcurrentexploit and12/4critical,10dev-onlyaudit snapshots remain provenance. Final `npm-audit-final.json` **0allseverity/emptyvulnerabilities** supersedes currentauditstatus,not futuresecurityguarantee. Typecheck120testsbuildPASS;Monacolargechunkwarningretained. No unsupplied completed Pythonregistryauditclaim.
- Wheel-finalbuilt andisolatedinstalledwheelHTTPcatalog31PASS usingexplicitexternalbrandingconfig,no repositorymodulepathfallback,provider0/learnerexecution0. Import/packaging success is not acceptedLinuxdeployment/rollback/security.
- Independentreviewers are **same-model** subagents,notCodex/crossmodelaudit. Known4security/2code/5functionalHIGHReact findings fixed/tested;publiccache andHTTPreplayguard narrowlyreviewed. Last2Replaybounds/error fixes above remain explicitpendingvalidation ratherthan blanket allclear.

## Runtime / promotion boundary

Actualbefore/light/dark/mobilegeometry,booleanhidden-confirmation/unavailable/restore anddraftresume evidence predate finalcache/guard/Replay/toolchainpatches. Existinghttp://127.0.0.1:5180/library preview runs earlier-loadedbackend. Browserclassifieroutage prevents stop/restart/mobileviewportreset: **final-source runtime refresh BLOCKED_TOOL**. Corelayout/UIobservations not finalpatchedbackendacceptance. Userstops onlyowned8020/5180previews orwaits toolrecovery,then deliberatelyrelaunches/revalidates.

Parentowns source/evidence/browser/checkpoint;expected futurelocal `evidence/workspace-expansion-20261114/checkpoint/CHECKPOINT_MANIFEST.json` notclaimedcreatedbydocs. Historical source/checkpoint/401-only reports retain snapshotidentity;no priorverifiedrelease overwritten. NoGitcommit/push/Drivepublication/publicpublish/sharingchange/paidprovision/submission. PrivateDB/backups/sidecars/audio/cache/consent/identityrecords/secrets excluded from sourcearchives/docs. Brandingundecided,humancontributionsnotinvented,no masteryclaims.

[Status](IMPLEMENTATION_STATUS.md),[FR/NFR matrix](FEATURE_COVERAGE.md),[handoff](ACCOUNT_HANDOFF.md),[speech](GNANI_CAPABILITIES.md),[operations](OPERATIONS.md),[deployment](DEPLOYMENT.md).

## Historical ADR provenance — not blanket current acceptance

Historical entries retained below;mock timings never proved real <=150ms hardwarebarge-in.

### Phase0/1 remediation ADR-006–ADR-010

- **ADR-006 — Pure-stdlib in-sandbox tracer separation/R1:** moved InSandboxTracer,InSandboxTraceOutput,LEARNER_FILENAME to `exec_worker/runner/in_sandbox_tracer.py`,without backend/workerappimports;runnerimagecopies onlyrunner package.
- **ADR-007 — Deep Challenge.input_args immutability/R3:** FrozenDict/FrozenList in `backend/app/models/domain.py` blockmutation/calleraliasing while preservingJSONserialization.
- **ADR-008 — Prelaunchhash/specbinding/R4:** SandboxRunner._verify_request_bindings andverification/tracechecks reject mismatchedcodehash,casehash,entrypoint before sandboxlaunch.
- **ADR-009 — Metaclass-safe serializer/R5:** `_safe_type_name` accesses exact type-owned metadata without invoking custommetaclassname descriptors.
- **ADR-010 — Holdoutexclusion/R8:** boundedgeneratorseen set includes allstatic holdout hashes beforesearch.

### Phase2 voice foundation ADR-011–ADR-014

- **ADR-011 — Singleconcurrency/unknown tariff:** semaphore1,boundedFIFO10/6s,durableusageledger/reservations;UNKNOWN_UNVERIFIED_TARIFF notinvented rupees/remainingcredit.
- **ADR-012 — Captureattempt binding:** rerecord incrementscapture_attempt_id withoutchanging samechallenge logicalturngeneration;latecapturecannotreplacecurrentattempt.
- **ADR-013 — Dualtranscript/selfcorrection:** raw preservedverbatim,normalizedproposalrequiresconfirmation;selfcorrectionsflagged,not silently adjudicated.
- **ADR-014 — Separate capture/playback contexts:** stoppingcoachplayback mustnot suspendAudioWorkletmiccapture. <=150ms is a target,not historicmock acceptance.
