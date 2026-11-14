# Constrained packaging and external acceptance gates

**Last updated:**2026-11-14. **Overall IN_PROGRESS.** Packaging preparation/local installed-wheel checks are not public deployment or isolation acceptance.

## Final local snapshot / runtime distinction

Recorded workspace `evidence/workspace-expansion-20261114/final-checkpoint-checks/`: **503 backend PASS,207 worker PASS,120 frontend PASS,9 genuine gVisor/trace/execution SKIPS;17 PASS checks,0 FAIL,4 omitted/external markers**. Typecheck/build/drift/secrets/archive pass. Offline credential-free/omitted-live markers deliberate; accepted isolation/code evaluation genuinely blocked.

Python aggregate statement coverage **81.4403149% (7034/8637)**; frontend **81.05% statements (1703/2101),88.53% lines,77.29% branches,74.00% functions**. Statement thresholds met both,not all metrics; older under-80/mapper figures superseded,not averaged. Real-runsc acceptance/coverage remains partial.

Node24.21,Vite6.4.6,Vitest/coverage4.1.12,React plugin4.7.0,DOMPurify3.4.17;React18/Monaco0.57 unchanged. Scoped sanitizer override installed/reviewed compatible development versions;no forced major transitive override. Finalnpm audit0 all severity/empty vulnerabilities snapshot,typecheck120testsbuildPASS;Monaco chunk warning remains. No supplied completed Pythonregistryaudit claim or future vulnerability-free guarantee.

Wheel-final built and isolated installed-wheel HTTP catalog31 PASS using **explicit external branding configuration**,no repository module-path fallback,provider0/learnerexecution0. Explicit branding remains an installation input;wheel success does not prove Linux isolation/images/TLS/rollback or final browser runtime.

**Final runtime refresh BLOCKED_TOOL.** Existinghttp://127.0.0.1:5180/library preview uses earlier-loaded backend;browser evidence predates finalcache/guard/Replay/toolchain patches. Tool classifier outage prevented stop/restart/mobileviewportreset. User stops onlyowned8020/5180 previews or waits recovery,then relaunches/validates. Do not claim final-source genuine browser acceptance or latest patched backend running. Last2Replay-cache bounds/error-eviction fixes remained finalizing at summary cutoff;validate/rerun after anysource change.

Local startup alternatives: `implementation/scripts/start_local.py --preview --port 8020` or `--env-file /Users/dhaanish/Desktop/VIVA/.env --port 8020`;Vite explicit `VCC_PREVIEW_API_TARGET=http://127.0.0.1:8020`,port5180. Exact absolute commands in [ACCOUNT_HANDOFF.md](ACCOUNT_HANDOFF.md). Startup selects serverconfig,not authorization fornewprovider calls. Filecanonicalcredentials override ambientaccounts/placeholders reject;`.env` preserved0600. Standard model startup needs VCC_GROQ_API_KEY,VCC_LLM_MODEL,VCC_LLM_PROVIDER=groq,key/modelmissing;liveQAforceddeterministic notmodelacceptance. Currentfallback noGroqcall.

No Docker daemon/no saved SSHtargets/no dedicatedauthorizedLinux/runsc host;customexecution disabled. Final authored sourcefixtures AST-only;earlier120host-subprocess fixtures stopped/removed,not acceptance. Genuine bounded Gnani protocol success separate from deployed/human acceptance. No weaker host/ordinary-Docker/AST fallback.

Commands below are future **operator-only runbook**,not executed by this docs pass and not authorization to provision/pay/publish/push/submit. Current scope localonly,noDrivepublication. No secrets/liveDB/backups/audio in archives. Preserve historical checkpoint identities;expected parentlocalmanifest notclaimedcreatedbydocs.

## Supported topology and trust boundary

Dedicated LinuxDockerhost with Linux5.6+ and supportedx86_64/ARM64 gVisor. DockerDesktop/macOS,remoteDOCKER_HOST,nestedDocker-in-Docker and ordinary-Docker/host-interpreter fallback not supported by this packaging. Worker uses hostDocker socket for fresh `--runtime=runsc --network=none` learner invocations;coordinator/frontend never receive socket.

Worker copies official Docker28.5.2 CLI,does not run daemon. Host/client APIcompatibility must be verified. Trustedworker is root/host-root-equivalent throughsocket;read-onlyroot/droppedcapabilities do notremove authority. Dedicatedhost must not contain unrelatedworkloads/credentials. Learner containers get only ownread-only `/ipc_in`,bounded `/tmp`tmpfs,no control-plane secrets,sourcecheckout,parentIPC,runtime orDocker socket. Worker includes sharedbackendverification package,not backendDB/routes/tests/secrets.

## Host gVisor bundle — explicit verified installation

Choose approved specific pointrelease/architecture,record version andverified upstream SHA512/SHA256. Download into new empty stagingdirectory,inspect archives/checksum before extraction/execution;keep scripts outside untrusteddownloads,use isolated interpreter(-I) for readers. No floatinglatest or unverified tool execution.

Install complete bundle(root-owned,no untrustedwrites)at `/opt/vcc/gvisor`:runsc,containerd-shim-runsc-v1,gvisor-bin sidecars kept together. Lonelegacybinary insufficient. Operator uses verified runscinstall/reloadsDocker,preserves existingdaemonsettings. No imagebuild installsruntime/configuresdaemon.

Confirm before startup:

- `/opt/vcc/gvisor/runsc --version` succeeds,records approvedrelease.
- `docker info --format '{{json .}}'` reports Linux daemonID and Runtimes.runsc.path exactly `/opt/vcc/gvisor/runsc`.
- Verifiedbundle can launch actual no-network gVisorcontainer.

Compose mounts same hostruntime read-only atsamepath;workerPATH probes hostbinary/bundle,not secondbakedruntime. Immutable baseimage digests/dependency scans/approvedruntime remain releasegates;versiontags are not auditeddigests.

## Shared IPC paths and cleanup

DefaultVCC_IPC_PARENT_DIR `/var/lib/vcc/ipc`:source,target,env must be exactsameabsolute nonsymlinkpath. Daemon resolves child bindmounts onhost;worker-private/tmp or differentlymountednamedvolume incorrect. Compose create_host_path:false avoids silentmissingpath creation;operator provisions:

| Host path | Permissions / use |
|---|---|
| /var/lib/vcc/ipc | root0700,sameabsolute writableworkerpath |
| /opt/vcc/gvisor | root/no untrustedwrites,executablebundle,samepathread-only |
| /var/lib/vcc/acceptance | root0755,initiallyempty,mount/etc/vcc/acceptance:ro |
| /var/lib/vcc/reports | root0700,dedicated acceptance reports |

IPC gate rejects relative/missing/symlink/wrongowner/non0700parents;production refusesprivate/tmpfallback. Randomizedjobdir0755,payload0444 so sandboxUID65534 reads ownroot;parent0700blocks otherhostusers and sandbox cannotreachparent.

Each invocation removesjobdir in finally,includingtimeouts/cancel;cleanupfailurelogged. Aftercrash,stopworker,inspect/remove onlyorphanedvcc-sbx containers andvcc_ipc directories in dedicatedparent. No sharedIPC deletion whilejobactive;no pruning unrelatedDockerresources.

## Future build/wiring — operator approval required

From implementation,copy `.env.example` to privateuntracked `.env`,supplyrandominternalworker secret outofband. Blankoptionalkeys meanunavailable,not placeholderlivecredentials. CORS exactpackagedoriginhttp://localhost:8080(orapprovedHTTPS),not implicitdevelopment5173. KeepVCC_ALLOW_PUBLIC_CUSTOM_CODE=false onbothservices.

```sh
docker compose config --quiet
docker build -f exec_worker/Dockerfile.runner -t vcc-runner:phase1 .
docker compose build
docker compose up -d
```

Never publishinterpolatedComposeoutput. Runnerimagebuiltseparately;workerinspectstagtoimmutableimageID andlaunchesinspectedID,avoids tagswitch. Frontend127.0.0.1:8080 onlypublished;coordinator8000/worker8001 internal. Sameorigin/api proxy preservesprefix,WSupgrades,unbufferedaudio,noAPIcache. Loopback8020/5180 developerpreview is separate topology,notdeployment.

## Explicit identity-bound real acceptance

Absentmarker expected. Nevermakeempty/example/successmarker or convert skip/mock/offline intopass. Only privilegedoperator issuesattestation afteractualzero-skip acceptance onexactDockerhost/runtime/runnerimage. Marker words alone notproof.

Future accepted-host test example(usingbuiltworker production socket/IPC/runtime,readonlytests,dedicatedreports):

```sh
docker compose run --rm -T --no-deps \
  -e VCC_ALLOW_PUBLIC_CUSTOM_CODE=false \
  -e VCC_RUN_LIVE_GVISOR_ACCEPTANCE=1 \
  -v "$PWD/exec_worker/tests:/workspace/exec_worker/tests:ro" \
  -v /var/lib/vcc/reports:/acceptance-reports \
  exec-worker python -m pytest \
  exec_worker/tests/test_sandbox_isolation.py -v \
  --junitxml=/acceptance-reports/gvisor-isolation.xml
```

Require selectedtests actuallyrun/pass withzeroskips/errors/failures/zeroexit;retainJUnit,source revision,operatorreview. Liveflag makesmissingruntime failure,not skip. Fixedsafeprobe alone isn'tadversarialproof;furthersecurity/trace/browser acceptance required. Learnerfixtures onlyfreshno-network runsc,no host/workerinterpreter fallback.

Atomicallyinstall reviewedhost `/var/lib/vcc/acceptance/accepted.json`,0444/read-onlymount,with:

| Field | Requirement |
|---|---|
| status / runtime | VERIFIED / runsc |
| adversarial_acceptance_passed / passed | exactJSONbooleans true |
| verified_at_utc | actualUTCacceptance time |
| acceptance_tests | reviewedtestnames,zero-skipcounts,reportSHA256,source revision |
| runner_image_id | exactimmutable inspectedsha256imageID |
| runsc_sha256 | SHA256 of /opt/vcc/gvisor/runsc |
| runtime_bundle_sha256 | packagedruntime_bundle_sha256 helperresult |
| runtime_version | exactrunscversion firstline |
| docker_daemon_id | exactDockerdaemonID |
| runtime_config | exactDockerRuntimes.runsc object,path,args |

Bundlehash isbinary plus sortedregular gvisor-binfiles,relativeUTF8path+NUL+binarySHA256digest;symlinksrejected,usepackagedhelper. Marker isoperatorattestation,not signedproof/hostile-rootdefense. Noofflinegenerationofacceptance.

Onlyafteractualgates,approvedoperator may enableVCC_ALLOW_PUBLIC_CUSTOM_CODE and recreatebothservices. Worker demandsreadonlymarkerfs,freshLinuxdaemon/image/runtime/binary/bundle/version match;authenticatedhealth acceptance_verified true onlyafterchecks. Coordinator usesauthenticatedresult+sameattestation,not markerpresence. Invalidate/rerun after relevantimage/runtime/sidecar/daemon/code/securitypolicy changes. Mismatchdegrades,no runcfallback. Operatorintegrity required;runtime registration canraceprobe.

## HTTPS/browser/rollback — still external

LoopbackproxyHTTPonly. Nonlocalmic requiresrealHTTPS;operatorapprovescertificates/TLS/redirects/trustedforwarding/HSTS afterverification,readonlycertmounts,noimage/sourceprivatekeys. No domain/cloud/tunnel/sharelink/443listener/certificate provisionedhere. Auth/abuse/release securityreview before exposure.

CSP useslocalMonacoworkers,self/blob audio,inlineMonacostyles,notCDN/unsafe-eval;connect-src self. VerifyexactapprovedWS/WSSorigins,targetbrowserworkerloading,recordingpermission,WAV/streamingunderfinalTLS;don'tusewildcards. PackagedNginx/browserTLSnotaccepted.

Privateonlinebackup/restore and migrationidentity controls in [OPERATIONS.md](OPERATIONS.md) arelocaltested,not deployedrollbackacceptance. Restore newinactivepath,neveroverwrite liveDB;validateversion/configandplannedrollbackonaccepteddeployment. Wheel31catalogpass isn'tfullcleanLinuxinstall/security/rollbackproof.

## Remaining acceptance and privacy

31 distinctproblems32specs/173curated64transfer626generated/31examples31bug31alternatives data/oraclesvalid;runtimeall31pending. Original12bug/atleast6alternatives separate. Coverage/build/packaging/protocoldoubles not isolation.

Four speakerslots0consent/24clipslots0recordings,6–8classmates needed;no physicalhumanmic/speakercheck/study. Synthetic7/7programmingtokens/Tamilimperfection and3.84sWebAudio/timeddebugstop nothumanaccuracy/NFRperformance/foregroundguarantee. Groqkey/modelmissing,fullWCAG/browser/device/latency/capacity/evaluator/TLS/realhost/finalruntime refresh andlast2Replay validation remainopen.

Parentowns expectedfuturelocalcheckpointmanifest;historical source/checkpoint artifacts remainprovenance. NoDrivepublication/gitcommit/push/publicpublish/paidprovision/submission. Neverinclude `.env`,liveDB/backups/sidecars,audio/cache,consent/identity/private transcripts in sourcearchives/docs. Same-modelreviews notCodexaudit. [IMPLEMENTATION_STATUS.md](IMPLEMENTATION_STATUS.md) and [FEATURE_COVERAGE.md](FEATURE_COVERAGE.md) retainallmandatorygates.
