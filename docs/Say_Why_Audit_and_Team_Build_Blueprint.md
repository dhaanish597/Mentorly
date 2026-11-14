# Say Why — audit and two-person build blueprint

Prepared for Dhaanish and teammate • 12 November 2026 • IST

## Decision

Keep the selected coding-coach direction. Replace **Viva-Setu** with the working name **Say Why**. Position it as **“Code it. Explain it. Back it up.”**

The product is a spoken coding practice environment: the learner predicts what their code will do, the application executes a relevant test, and the learner explains and repairs the difference. It uses Gnani speech recognition and synthesis, execution evidence, and a follow-up problem that checks whether the learner can apply the idea again.

This is a refinement recommendation, not an implemented application. The team now has two members; the solo schedule and inherited rankings in Gemini's report are obsolete planning inputs. Shortlisting cannot be guaranteed. The official page describes selection through verified engagement among eligible projects, with individual interviews afterward [S1–S2].

## What this audit covers

Reviewed the supplied **61-page Gnani Challenge Final Invention Round(1).pdf**, including its architecture, comparison matrices, candidate variants, evaluation design, schedule, bibliography, and image-only charts on pages 29, 35 and 50. Rechecked the decision-critical competition rules, Gnani interfaces, testing semantics, tracing behavior, important research references, and selected competitors against primary sources. Executed two small trusted local algorithm checks to examine the report's demo assumptions.

This is a full-document substantive review, not independent verification of all 105 bibliography entries, all competitor features, or every numerical paper result. No paid competitor accounts were tested. No Gnani account credentials were provided or live Gnani requests made. Brand/domain/trademark availability is not established. Proposed thresholds below are acceptance targets, not measured performance.

## 1. Naming and positioning

**Recommended: Say Why.** Short, conversational, easy to say in a demo, and directly connected to explaining an algorithm. Use the subtitle **A voice coding coach that checks your reasoning against execution.**

Alternative descriptive names are **Walk Me Through** and **On the Spot**. Do not spend the build window choosing among dozens of names. A limited search found a directly overlapping interview product using DryRun, so avoid that otherwise appealing name [S15]. Searches did not establish exclusive rights to any proposed name.

Do not claim “the first AI interviewer,” “the only counterexample tutor,” “zero hallucinations,” “guaranteed placement,” or “proves your understanding.” Prefer: **“For our supported Python exercises, Say Why links spoken predictions to actual execution, helps you repair mistakes, and checks your reasoning on a fresh example.”**

The strongest audience hook is: **Your code passes the examples. Can you explain the case that breaks it?**

## 2. Findings that must change the implementation

P0 means a blocker before public use or before making the claim. P1 means an important correction. P2 means scope or presentation improvement. Findings described as analysis are deductions from the proposed design, not vendor admissions.

| ID | Priority | Report claim or design | Audit finding and required correction |
|---|---|---|---|
| A01 | P0 | 200 passing Hypothesis cases establish correctness | Finite testing is evidence within a defined input domain, not general proof. Display actual executed counts, tested constraints and “no failure found in this run.” Keep unsupported and inconclusive outcomes. |
| A02 | P0 | `max_examples=200` means exactly 200 tests/properties passed | Hypothesis may stop early or execute additional shrinking/replay calls. Instrument valid examples, executions and replay separately. Test cases are not distinct properties [S7]. |
| A03 | P0 | The shrinker guarantees the globally smallest counterexample in under 350 ms | A simplified failing example is useful; global minimality and a fixed runtime are not established. Bound search time, retain a reproducible failure if shrinking times out, and measure deployed latency [S8]. |
| A04 | P0 | Compare student/reference locals line by line to find the exact bug | Valid algorithms can have entirely different variables and control flow. Compare outputs; trace the student's actual program. Use annotated checkpoints only for curated templates. Label generic localization as a hypothesis. |
| A05 | P0 | A subprocess with stripped built-ins is a sandbox | It is insufficient for hostile public submissions. Use an isolated execution boundary with no application secrets, no network, bounded resources and a restricted filesystem. Even RestrictedPython explicitly disclaims being a sandbox [S10–S11]. |
| A06 | P0 | The hero example `[-2,0,-1]` exposes the described overwrite bug | A reconstruction of the usual bug returns 0, matching the reference. The report supplies no exact function that produces its claimed -2. Derive demo artifacts from executable fixtures; see section 3. |
| A07 | P1 | AST plus phonetic score 0.72 identifies true conceptual errors | Identifier similarity does not determine a person's intent or comprehension. Use it to propose a token mapping; ask for confirmation when ambiguous. The threshold is uncalibrated. |
| A08 | P1 | Correct code plus a bad explanation proves “vibe-coding” | It may reflect a speech error, nerves, ambiguity or misunderstanding. Do not accuse or infer authorship. Ask a specific prediction question and record the response. |
| A09 | P1 | Passing the repaired code proves misconception repair | A copied patch can pass. Require a fresh prediction/explanation before revealing a new execution result. Describe the result as evidence on that task, not long-term learning. |
| A10 | P1 | All developer accounts allow exactly one request across every endpoint | Official limits defer to the account and organisation; TTS documentation includes a one-active-request error example. Inspect and test the actual account. Serialization is a conservative fallback, not a proven universal restriction [S3,S6]. |
| A11 | P1 | `asyncio.Lock()` prevents all 429 errors | A lock is process-local and does not cover another worker, teammate's script, rate quotas or other services. Use account-aware scheduling, bounded retries and a shared queue if required. Do not lock the entire student session. |
| A12 | P1 | Streaming plus `InterruptibleTTSService` guarantees real-time correction | A transport adapter does not solve semantic judgment, audio cancellation or timing. Start with a complete user turn. Measure proactive interruption separately, if added. |
| A13 | P1 | Total latency is 1,035 ms / below 1.3 s | Page 50 presents estimates without local measurements and omits or obscures end-of-turn and repair delays. A 1-second silence threshold plus extra hold plus inference can exceed the headline. Publish timestamps and actual p50/p95 only after measurement. |
| A14 | P1 | Three-and-a-half-second repair hold and sub-second correction coexist | They are competing interaction choices. Favor user-controlled completion initially; add adaptive waiting only after testing. Preserve self-correction rather than engineering dramatic interruptions. |
| A15 | P1 | Speech context options work identically across raw API and plugins | The raw streaming documentation allows fixed context headers and specific mid-session updates; the SDK/plugin surface differs. Implement against one pinned interface and test acknowledgements [S4–S5]. |
| A16 | P1 | Blind suffix stripping/substitution improves technical speech | It can change identifiers or erase meaningful language. Keep raw transcript, normalized proposal and user-confirmed claim separately. Protect numbers, comparisons, negation and code identity. |
| A17 | P1 | `sys.settrace` directly gives post-line state and exact fault cause | Line callbacks occur before execution. Capture the next event appropriately and snapshot mutable values. A trace is observation, not automatic causal diagnosis [S9]. |
| A18 | P1 | Generic AST extraction supplies input specifications | A signature does not establish semantics or legal domains. Each supported exercise needs a versioned specification, trusted oracle, comparator and generator. |
| A19 | P1 | Sorted order plus unchanged length verifies sorting | A constant-output function can satisfy both for some domains. Also verify preservation of elements/multiplicities. Other tasks need suitable invariants, not arbitrary round-trip properties. |
| A20 | P1 | Tests determine asymptotic complexity | Finite executions can illustrate operation counts, not generally prove Big-O. Restrict complexity feedback to reviewed task reasoning and explicitly supported cases. |
| A21 | P1 | Baseline v2.5 vs tuned v3.0 isolates the new method | Model, language hints, format and normalization all change. Hold the model and audio fixed for feature ablations. A model comparison is a separate experiment. |
| A22 | P1 | Competitor features absent from a web page are absent from products | Not established. Additional coding tutors already combine tests, coaching and voice practice. Claim the implemented workflow and measured improvements, not universal exclusivity [S12–S16]. |
| A23 | P1 | Prior-art papers make the whole pipeline a new invention | Socratic contradiction and debugging trajectories already exist [S17]. Attribute them. The team's contribution is the implemented voice/evidence/learning workflow and its measured behavior. |
| A24 | P1 | Old composite scores and uncertainties justify the final choice | These were subjective scores for earlier variants and solo assumptions. They are neither measurements nor calibrated confidence intervals. Replace them with delivery gates and qualitative rationale. |
| A25 | P1 | An 11-entry scan proves nobody in the contest built this | A public sample cannot establish the full submission pool or hidden features. Retain entries as examples of prior art, not an exhaustive census. |
| A26 | P1 | A second Prisma transcript is an oracle | Two recognitions can agree and both be wrong. Use human-checked references for an evaluation harness; disagreement is a diagnostic signal, not truth. |
| A27 | P1 | A fixed random seed guarantees identical remote API outputs | It fixes the generated input, not a remote model, service version or timing. Store the exact audio, settings, versions and outputs. Built-in Python `hash(text)` is not a stable cross-process seed by default. |
| A28 | P1 | A TTS final event proves the user heard the obligation | Server synthesis completion differs from browser playback completion. Track playback acknowledgements and cancelled segments; keep an unanswered question pending. |
| A29 | P1 | Fixing code cannot invalidate a pending voice response | The report omits version races. Bind every analysis, trace and spoken reply to code version, turn ID and specification version. Cancel stale results on edits. |
| A30 | P1 | A 1.5-second worker timeout proves non-termination | It proves a timeout in that environment, not an infinite loop. Kill the process group, cap output and classify TIMEOUT separately from wrong output. |
| A31 | P1 | Public traffic is compatible with a per-key lock and small credits | A reliable single-user demo may queue badly under sharing. Add fair admission, short sessions, cost caps, visible waits and an explicitly labelled recorded walkthrough. |
| A32 | P1 | Switch to an evaluation platform if the editor is difficult | A second product introduces a second user flow, data pipeline and story. Degrade within the selected coach: curated editable code, explicit turns, simple trace tables. |
| A33 | P2 | Three dense diagnostic panels improve the demo | “Disentanglement matrix” and a misconception DAG burden the student. Use code, a clear prediction/result card and a focused conversation. Put engineering evidence in an optional details view. |
| A34 | P2 | Sighs and dramatic interruption make a better teacher | They can sound impatient. Use neutral, supportive speech and let the learner finish. Treat expression tags as polish. |
| A35 | P1 | Self-recorded audio makes everything fully compliant | Self-recordings reduce data risks but do not establish blanket legal compliance. Do not repeat the report's legal conclusions. Minimize collection and get permission for recordings used in evaluation. |
| A36 | P1 | Solo work schedule and 73.5-hour budget still apply | User confirms two people and time has elapsed. Integrate on day one, launch early, reserve submission margin. Do not double a solo estimate and call it a team plan. |

## 3. Local execution checks performed in this audit

These are narrow, trusted fixtures written for the audit, not tests of a finished product, Gnani or Hypothesis. Hypothesis was not installed in the audit environment; no Hypothesis speed/result is claimed.

### Maximum-product example from the report

Reconstructed the common bug described in the PDF:

```python
def buggy(a):
    hi = lo = best = a[0]
    for x in a[1:]:
        hi = max(x, hi*x, lo*x)
        lo = min(x, hi*x, lo*x)  # wrongly uses the just-updated hi
        best = max(best, hi)
    return best

def reference(a):
    values = []
    for i in range(len(a)):
        p = 1
        for x in a[i:]:
            p *= x
            values.append(p)
    return max(values)
```

| Input | Buggy result | Reference result | Observation |
|---|---:|---:|---|
| `[-2, 0, -1]` | 0 | 0 | Does not expose this reconstructed bug. |
| `[-2, 3, -4]` | 24 | 24 | Another plausible example that does not expose it. |
| `[-3, -3, -3]` | 81 | 9 | Actual failure. Exhaustive search over integers -3 through 3 found no length-1 or length-2 failure for this fixture; first failing length was 3. |

The original PDF does not give the precise buggy source corresponding to its output artifact. Therefore the conclusion is not that every possible implementation passes its example; it is that the promised artifact is unsupported and does not follow from the described ordinary bug.

### Better hero scenario: shortest subarray reaching a target

For a common sliding-window function that advances the right endpoint and repeatedly shrinks while the sum reaches the target:

| Input and target | Sliding-window result | Brute-force reference | Observation |
|---|---:|---:|---|
| `[1, -1, 5]`, target 5 | 3 | 1 | `[5]` alone suffices; the proposed generalization to negative values fails. |
| `[2, -1, 2]`, target 3 | 3 | 3 | Negative input does not always expose the error. |
| `[2, 3, 1, 2, 4, 3]`, target 7 | 2 | 2 | Standard positive-only example passes. |

**Important:** only use the first case when the exercise specification explicitly allows negative numbers. If the original task allows only positive numbers, present this as an announced change of assumptions, not a bug in a valid solution.

This leads to a stronger demo: the student says the approach still works after negatives are permitted; the coach asks them to predict the result before revealing the executed mismatch.

## 4. Improved product: spoken prediction, execution evidence, transfer

### The complete interaction

1. Pick a supported Python exercise and read its constraints.
2. Write or load code and explain the approach aloud.
3. The system displays its interpretation of a testable statement. Confirm ambiguous identifiers or conditions.
4. The coach asks a concrete prediction: “What will your function return for this input?”
5. The application executes the exact code version and compares its result with the trusted task oracle.
6. The learner steps through the relevant execution, gets a graduated hint, and edits the code or revises the claim.
7. The application reruns the failing case and regression set.
8. The learner predicts/explains a fresh case before its output is revealed.

The educational advantage is a complete learning loop rather than immediate answer generation. The fresh case helps distinguish remembering a patch from applying a principle. Any learning-effectiveness claim still needs a proper study.

### Three improvements to make central

**Predict before revealing.** Commit the student's spoken prediction before showing output. This gives the conversation a testable object and makes the demo intelligible.

**Make the coach correctable.** Show what was heard and what claim was inferred. “I meant `min_prod`, not `max_prod`” must repair the claim without blaming the student. Retain raw speech-derived text; no silent replacement of negation or numbers.

**Check a fresh case.** A repaired code result and a new explanation are separate observations. Show both, rather than a single invented confidence score.

### Initial scope

- One browser application, Python only, three reviewed exercises.
- English and Tamil-English first, reflecting accessible testers. Add Hindi-English only after actual testing and a competent reviewer; do not claim equal support without evidence.
- Exercises: shortest qualifying subarray with explicit domain change, binary-search boundary handling, maximum-product subarray.
- Every exercise has a versioned specification, brute-force or otherwise reviewed reference, generators, canonical output comparison, bug fixtures, alternative valid solutions and teaching checkpoints.
- Spoken prediction, actual execution, a compact trace, graduated hints, edit/retest, one fresh transfer question.
- Real Gnani STT and TTS; optional fast text model for interpretation and phrasing. The model does not determine executed values.
- No compulsory login for the short demo. Admit sessions according to real capacity.

Exclude system-design interviews, arbitrary algorithm verification, many programming languages, voice cloning, biometrics, universal complexity proofs, clinical claims, leaderboards, hiring scores and a second evaluation-platform product.

## 5. Architecture corrections

### Approach chosen for this recommendation

Use a turn-based browser voice coach with execution-backed challenges. This is more achievable than continuous proactive interruption and more substantial than a generic interviewer. User-controlled “Check my reasoning” completion is the reliability baseline; natural pause detection can be added without removing that control.

**Browser:** code editor, transcript/prediction confirmation, microphone controls, audible coach, input/output/trace panel. Keep technical diagnostics out of the main learning flow.

**Coordinator:** session and turn state, account-aware Gnani scheduling, task definitions, claim schema validation, artifact store and cancellation. Raw speech, parsed interpretation, observed execution and generated explanation are separate records.

**Verification worker:** isolated execution service or properly configured sandbox worker. The controller chooses bounded inputs and compares serialized output against a trusted oracle outside the student-code trust boundary. Never trust assertions or “passed” messages supplied by student code. No secrets, network or shared writable application filesystem in the execution environment. Bound CPU, memory, process count, output, trace size and wall time [S10–S11].

**Coach:** uses verified artifacts to phrase questions; a deterministic template is available for each supported failure type. If interpretation is uncertain, ask. If execution fails operationally, say so. Comments in student code and transcript content are untrusted inputs, not coordinator instructions.

**Evidence artifact:** task/spec version, code hash, turn ID, confirmed prediction, input, student output, oracle output, verification status, trace-event IDs, test configuration and timing. Exclude raw audio from default retention; make recording for evaluation optional.

**Statuses:** CLARIFICATION_NEEDED, UNSUPPORTED_CLAIM, COUNTEREXAMPLE_CONFIRMED, NO_FAILURE_FOUND, EXECUTION_ERROR, TIMEOUT, PATCH_PASSES_RUN, TRANSFER_RESPONSE_RECORDED. Never collapse all of these into red/green correctness.

**Learning state:** prediction captured → evidence shown → hint requested/given → revision → rerun → fresh prediction. This is an interaction state machine, not a diagnosis of the learner's mind.

### Speech integration

Prisma v3.0 context and Timbre v3.0 synthesis are documented, but access and speed must be measured on this account. AST-derived terms can help name recognition; they do not prove understanding. The raw WebSocket and plugin options must not be conflated [S3–S6]. Use a backend proxy for credentials and validate the actual model returned. Log ignored/unsupported options where possible.

Measure latency from the last voiced sample or explicit submit to first audible response, including turn completion, queue wait, STT, verification, generation and playback. Also show first visible evidence time. Report cold and warm cases separately. A target is not a guarantee.

On code edit: invalidate stale work. On interruption: stop browser playback promptly, discard stale audio, preserve unanswered obligations. A synthesis `is_final` event is not evidence that playback finished.

If concurrency is one, provide honest queued admission and short turns. One `asyncio.Lock` inside each of several server workers cannot enforce a global limit. Do not send both teammates' test scripts against the same key without coordination.

### Fallbacks within this product

- Streaming unreliable → explicit short recorded turns through REST.
- Fancy animation slow to build → table of real values with step buttons.
- Broad automatic claim parsing unreliable → supported prediction types plus confirmation.
- Public arbitrary-code execution not isolated → do not expose it; provide reviewed code variants and permitted edits without arbitrary execution until isolation is ready. Label the actual scope.
- API capacity limited → a live queue and clearly labelled recorded walkthrough, never a prerecorded answer presented as live.

## 6. Evaluation that supports a defensible demo

These are proposed small-sample acceptance gates, not results or estimates of universal reliability.

| Area | Initial test | Acceptance target |
|---|---|---|
| Verification | 12 reviewed buggy fixtures across three exercises plus at least six alternative valid solutions | Every shown failure replays against the exact code/spec; no correct alternative is rejected for internal trace differences. |
| Transcript/claim handling | 24 human-recorded clips from four or more consenting speakers, including self-correction, negation, numbers and identifier ambiguity | No known ambiguous critical token is silently used to accuse the learner. Report actual semantic-field errors and clarification count. |
| Coaching | Correct answer, wrong prediction, code slip, incomplete thought, self-repair, unexpected follow-up | No unsupported wrong/correct verdict; useful clarification or evidence-backed question. |
| State consistency | Edit code while analysis runs; interrupt audio; retry requests; switch problem | No stale trace or spoken correction is applied to a new code version. |
| Execution safety | Timeout, oversized output, recursion/memory pressure, filesystem/network attempts in a controlled sandbox test | Isolation and limits behave as configured before public editable-code access. |
| Experience | 20 complete live turns including cold starts and failures | All outcomes visible; publish actual completion and latency distributions. Aim for a typical response within roughly 3 seconds after explicit completion, then revise based on measurements. |
| User value | 6–10 classmates try a short session | Report completion counts, confusion points and exact feedback; no claim of proven placement or learning gains. |

Keep a development set separate from held-out examples and speakers. Use the same clips and model for feature ablations: baseline → task/identifier hints → confirmation workflow. Measure tradeoffs: fewer false corrections may require more questions or more time. Compare against a simple LLM voice-coach baseline without claiming it represents Chakra or every commercial product. Human-check semantic labels. Store exact generated inputs and configuration so the results are reproducible.

## 7. Stronger 60-second demonstration

| Time | What the viewer sees/hears |
|---|---|
| 0–6 s | Working app already open. “My code passes the examples. But does my explanation hold up?” |
| 6–14 s | State the problem-domain change: negatives are now allowed. Student explains why they think the sliding window still works, naturally in Tanglish. |
| 14–23 s | The coach confirms the relevant claim, shows `[1,-1,5]` with target 5, and asks for the output prediction. |
| 23–34 s | Real execution shows the current function returning 3 while the reference finds length 1. The trace shows why the window misses `[5]`. |
| 34–47 s | Student explains the broken assumption, makes a supported repair or revises the approach; live rerun shows actual outcome. |
| 47–55 s | A fresh example asks the student to predict again. The UI separates code-test evidence from explanation evidence. |
| 55–60 s | “Say Why — Code it. Explain it. Back it up.” Show real Gnani usage and invite viewers to try the short challenge. |

Record only after the complete interaction is reliable. The 60-second version may have clearly apparent editorial cuts; do not splice them to imply false latency or success. Keep a longer uncut working session available. If the repair cannot fit honestly, prioritize prediction, execution and the student's insight; show the repair in the longer recording.

Do not display a false “200/200 properties proved” badge. Do not stage an ASR mistake as naturally observed unless it actually occurred. Preloaded exercises are legitimate when disclosed; hardcoded fake verifier results are not.

## 8. Two-person delivery plan

Suggested ownership reflects work streams, not assumptions about your teammate's skills. Swap leads if needed.

| Work stream | Lead | Required partner review |
|---|---|---|
| Task specifications, reference oracles, execution worker, replayable evidence | Dhaanish | Teammate reviews failure fixtures and correct alternative solutions. |
| Browser audio, Gnani adapter, editor/trace UI, turn lifecycle | Teammate | Dhaanish reviews timing, code-version races and quota handling. |
| Integration, adversarial cases, demo, evaluation, submission | Both | Each explains the full pipeline and records actual contributions. |

Do not leave one teammate with only video and marketing. Both need substantive engineering ownership and individual interview readiness [S2].

### Milestones from the evening of November 12

- **First 90–120 minutes:** one real STT/TTS turn, one genuine failing-input replay, an execution-isolation decision, agreed request/result schemas. Test actual account access and determine whether the chosen voice/language works.
- **November 13 morning:** one complete vertical slice: spoken prediction → actual execution → trace → spoken question. Integrate now, not after separate front/backend completion.
- **November 13 afternoon/evening:** three exercises, false-correction handling, stale-result cancellation and initial classmate sessions. Deploy a controlled preview early to discover hosting/audio issues.
- **November 14 morning:** repair observed problems, run held-out evaluation, verify public capacity and recording permissions. Freeze scope.
- **November 14 afternoon, target 15:00–18:00 IST:** publish the working video and trial link. This is our planning target, not an official posting deadline.
- **November 15 morning:** respond to genuine questions, maintain uptime, verify nominee links and member details. Target submission by 12:00 IST; retain confirmation. Published official cutoff is 18:00 IST [S1–S2].

If the first milestone fails, reduce the interface or turn mechanism within Say Why. Do not automatically switch to building an unrelated evaluation product.

## 9. Shortlisting strategy grounded in the rules

The official process separates project shortlisting, individual offers and category awards. It does not publish a guaranteed engagement threshold or the weight of each reaction type. Do not invent one [S1–S2].

Use one clear nominated post per platform. Credit both teammates and concentrate the team's outreach on the nominated URLs; do not assume several separate posts' engagement will be aggregated. Both teammates should verify their participation details and the organiser's acceptance instructions.

Make the product easy to try: a short challenge, a ready exercise, a visible microphone permission explanation, and a clear queue if capacity is limited. Ask classmates for real testing and feedback. Share in college coding communities and with faculty/alumni where welcome. Show the verified counterexample and what you learned, not an architecture slide full of invented scores.

No purchased engagement, paid promotion, exchange groups or automated reactions. No messages have been sent on your behalf by this audit. Track genuine visits, sessions completed, issues reported and comments received; these are operational signals, not selection probabilities.

Most defensible award fits: Two-Person Army, Mixed Vibes if demonstrated, Demo Day Drop, and possibly Jugaad Genius. Do not force a telephony or small-town category merely because it exists; eligibility and judging remain the organiser's decision.

Reliability is part of distribution: preserve credits, bound session lengths and keep one stable public build available. A viral link that fails for testers harms the story.

## 10. Review of the other candidate families

They are not rejected because competitors exist. They are deferred because the user has selected the coaching direction and its evidence/access path fits this team.

| Direction | Useful lesson retained | Concern in the final report |
|---|---|---|
| C01 agent evaluation | Reproducible inputs and explicit state checks | A tuned transcript is not ground truth; patches cannot be promised to turn all tests green. Keep an internal evaluation suite, not a second product. |
| C03 speech assistance | Respect pauses and user agency | Synthetic stutters and a louder/longer VAD setting do not validate real accessibility outcomes; no automatic claims about intent or clinical benefit. |
| C04 electronics | Ground actions in structured source data | Pin mapping and “safe readback” do not validate electrical safety. Real hardware/data and expert review add dependency. |
| C05 machine acoustics | Multimodal observations can aid diagnosis | Seeded spectral faults and an uncalibrated chirp do not validate real machinery diagnosis. |
| C06 incidents | Explicit approval and pending-task state | A spoken token alone does not authenticate authority. Tool/result provenance and permissions remain necessary. |
| C07 meetings | Track revisions rather than just summaries | Distinguish superseded decisions from contradictions; speaker-name hints are not live speaker identification. |
| C08 policy checking | Trace claims to a precise source | Regulation summaries and numeric rules need product/date context; do not treat illustrative examples as legal conclusions. |
| C09 acoustic receipt | Bind outputs to auditable artifacts | At the report's own 8–16 bytes/s, 2.5 seconds provides about 20–40 bytes before overhead, insufficient for many ordinary signed JSON cards. Specify payload and threat model. |
| C10 consent | Ask users to explain back | Hesitation is not a validated measure of comprehension or consent. Clinical workflow requires evidence and human responsibility. |
| C11 ordering | Clarify high-impact ambiguity before commit | A second transcript is not truth; substitutions, stock and budget preferences need explicit priorities. |
| C12 web access | Confirm actions and recover state | Live third-party portals add access, layout and transaction dependencies. A controlled demo cannot imply universal navigation. |
| C13 lectures | Resume the interrupted task | Timestamp proximity does not establish answer correctness. Lectures/materials need permission and source-grounded checks. |
| C14 spoof protection | Evaluate attacks under realistic conditions | The revised report reintroduces cloning embeddings as verification and says a challenge “defeats” real-time cloning without evidence. Do not carry that mechanism forward. |

## 11. Sources and evidence boundaries

Sources accessed 12 November 2026. Links support the specified narrow facts; they are not blanket endorsements of the proposed product.

- **S1:** [Gnani challenge page](https://www.gnani.ai/internship) — deadline, selection, category and submission mechanics.
- **S2:** [Gnani participation terms](https://www.gnani.ai/great-indian-ai-internship-registration-form) — team details, credits, individual outcomes and authenticity.
- **S3:** [Gnani STT limits](https://docs.gnani.ai/api/STT/limits) — account-specific limits and documented request constraints.
- **S4:** [Gnani raw streaming API](https://docs.gnani.ai/api/STT/stt-websocket) — context headers, control updates and segment events.
- **S5:** [Gnani Pipecat integration](https://docs.gnani.ai/pipecat/introduction) — adapter behavior and language-candidate guidance.
- **S6:** [Gnani streaming TTS](https://docs.gnani.ai/api/TTS/tts-sse) — model/voice parameters and sample concurrency error.
- **S7:** [Hypothesis test-case counts](https://hypothesis.readthedocs.io/en/latest/explanation/test-case-count.html) — generation, shrinking and replay counts differ.
- **S8:** [Hypothesis settings](https://hypothesis.readthedocs.io/en/latest/settings.html) and [shrinking strategies](https://github.com/HypothesisWorks/hypothesis/blob/master/guides/strategies-that-shrink.rst) — testing configuration and simplification.
- **S9:** [Python tracing documentation](https://docs.python.org/3/library/sys.html#sys.settrace) — line events precede execution.
- **S10:** [RestrictedPython](https://restrictedpython.readthedocs.io/en/latest/) — explicitly not a sandbox system.
- **S11:** [gVisor security model](https://gvisor.dev/docs/architecture_guide/security/) — an isolation boundary still needs restricted resources and permissions. No deployment or provider performance is claimed here.
- **S12:** [Chakra evaluation](https://candidatesupport.hackerrank.com/articles/3077231667-evaluation-in-chakra) — assessment, hands-on work, reasoning follow-ups and no in-interview correctness feedback.
- **S13:** [Python Tutor](https://pythontutor.com/) — execution visualization and teaching use; this establishes prior art for tracing interfaces.
- **S14:** [OphyAI coding practice](https://ophyai.com/coding-practice) — vendor describes real tests, coaching and spoken mock rounds. Not independently tested.
- **S15:** [DryRun Interviews](https://www.dryruninterviews.com/) and [InterviewDryRun](https://interviewdryrun.com/ai-coding-interview) — overlapping naming/category, voice/code practice. Not independently tested.
- **S16:** [Cynchrony](https://www.cynchrony.in/) — vendor describes interview and AI-assisted coding workflows; not independently tested.
- **S17:** [Reasoning Trajectories for Socratic Debugging](https://arxiv.org/abs/2511.00371), [full paper](https://arxiv.org/html/2511.00371v2) — contradiction-guided teaching is prior art; not every valid trajectory must instantiate a concrete failing input.
- **S18:** [Model Interruption Bench](https://aclanthology.org/2026.emnlp-main.2349/) — existence and general detection/interruption finding verified. It studies spoken math, not this project's coding protocol; its results cannot be adopted as our baseline.
- **S19:** [Joi-Bench-Task](https://arxiv.org/abs/2611.12118) — existence and task-coordination finding verified. An explicit pending-task list is inspired by the problem; it does not inherit an experimentally proven zero-omission guarantee.

The report's accessibility, medical, industrial and finance statistics were not needed to select/build this product and are not adopted here. Exact prior-paper chart values on page 29 should remain out of the pitch unless checked against the relevant tables and their evaluation conditions. The numerical shortlist chart on page 35 and latency chart on page 50 are not measured product evidence.

## Final build directive

Build **Say Why** as one coherent experience: **explain → predict → execute → inspect → revise → try a fresh case**. Make real execution and correctable speech interpretation visible. Freeze at three well-tested exercises, one programming language and demonstrated speech-language support. Both team members build and understand substantive components. Publish a reliable working demonstration early, then use genuine feedback to improve it.

Before public launch, the remaining critical checks are live Gnani account behavior, isolated code execution, end-to-end timing and actual users completing the workflow. Those cannot be replaced by this research or by a confident score.
