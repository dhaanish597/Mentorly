# The Great Indian AI Internship Challenge — Official Website Brief

**Source:** [Gnani AI internship challenge page](https://www.gnani.ai/internship)  
**Page reviewed:** 12 November 2026 (India time)  
**Purpose:** A structured, readable capture of the challenge information shown on the official page, including every expandable FAQ. This is a paraphrased reference, not a substitute for the registration terms.

> **Source hierarchy:** The challenge page says the full programme terms appear on the registration page and are the final word. Confirm details there before registering or submitting. The countdown displayed during review was dynamic (about 2 days, 21 hours remaining); the fixed deadline stated on the page is **15 November 2026 at 18:00 IST**.

## 1. Challenge at a glance

- **Official name:** The Great Indian AI Internship Challenge — “Build Sovereign AI for India.”
- **Organizer:** Gnani AI.
- **Challenge format:** Open brief. Participants choose a practical problem and build a working application using at least one Gnani AI model or API.
- **Who can participate:** Students enrolled in a degree or course at a college or university in India, who are at least 18 on the registration date.
- **Team size:** One participant or a team of exactly two. Both teammates must independently meet eligibility conditions.
- **Submission deadline:** **15 November 2026, 18:00 IST.**
- **Internship opportunity:** Up to 100 paid internships, each scheduled to run for six months from **1 January 2027**. The page advertises a stipend of **up to ₹1,00,000 per intern per month**; this is a ceiling, and the selected candidate’s exact amount is specified in their written offer.
- **Awards:** Ten categories, each worth **₹50,000** (₹5,00,000 total).
- **Registration credits:** Each registration receives **5,000 programme credits**. For a duo, credits are assigned to the primary registrant’s account.

## 2. What participants must build and submit

A valid entry is a real, working application built with at least one Gnani AI model or API and demonstrated publicly in a video. A concept-only entry or a misleading/non-working demo does not meet the page’s stated requirement.

The submission flow has four steps:

### Step 1 — Register

The registration asks for:

- Full name, email and phone number
- College, degree/course and discipline
- Year of study, graduation year and city
- Solo or team-of-two status; a duo provides the teammate’s email

Each teammate must accept the contest terms individually. In a team, the teammate’s email is used to verify eligibility and participation. Programme communications go to the primary registrant.

### Step 2 — Build

Project details to prepare:

- Project title
- Problem being addressed
- Intended users
- Gnani AI models or APIs used
- Each team member’s contribution

These project details can be edited until the final submission is made.

### Step 3 — Post a public demo

- Record a video showing the application working.
- Post it on LinkedIn, X, or both.
- Explain what was built and which Gnani AI technology it uses.
- Tag Gnani AI and include both `#GnaniAI` and `#GreatIndianAIInternshipChallenge`.
- The post must be live before submitting. Tagging Gnani AI alone is not an entry.

### Step 4 — Submit

The submission requires:

- The demo video
- A written project explanation
- The Gnani AI models or APIs used
- One nominated post link per platform used

The page describes a separate submission form; registration and final submission are distinct steps. Submit by **15 November 2026 at 18:00 IST**.

## 3. Awards

Awards are judged against their own category criteria, separately from internship selection. An individual or team can receive **at most one award**. Each award is ₹50,000. Purchased votes, bots and engagement exchanges do not count.

| Award | What it recognizes |
|---|---|
| **Main Character** | Best build in a regional or low-resource Indian language. |
| **Mixed Vibes** | Best code-mixed voice experience, such as Hinglish, Tanglish or Benglish. |
| **Real Deal** | Most useful real-world solution for users such as farmers, kirana stores or rural health workers. |
| **Noise Canceller** | Best performance on messy, noisy real telephony audio. |
| **Two-Person Army** | Best project built by a team of two. |
| **Solo Ninja** | Best project built by one participant. |
| **Jugaad Genius** | Most creative or unexpected use of Gnani AI models. |
| **Small Town, Big Build** | Best entry from a college or city in a Tier 2 or Tier 3 town. |
| **Demo Day Drop** | Best 60-second demo video. |
| **Crowd Favourite** | Public votes on LinkedIn and X using `#GreatIndianAIInternshipChallenge` and `#GnaniAI`. |

### Examples offered by the page

These are suggestions, not required problem statements:

- A Kannada voice helpline that reads crop and weather advisories to farmers (Main Character, Real Deal).
- A Hinglish voice assistant that takes phone orders for a neighbourhood kirana store (Mixed Vibes, Real Deal).
- A call summarizer designed for noisy phone audio and tested on synthetic calls (Noise Canceller).
- A Tamil voice tutor that quizzes students aloud and explains answers (Jugaad Genius).

## 4. Models and platform scope described on the page

Gnani says its models are trained for Indian speech and real telephonic audio, and are designed for noisy calls, code-mixed speech and Indian languages. The page presents the following challenge model options:

| Model | Page description | Link |
|---|---|---|
| **Prisma v2.5 — Speech to Text** | Trained on over 14 million hours of telephonic audio; streams in under 200 ms across 10+ Indian languages, plus Hinglish, Tanglish and Benglish, according to Gnani’s published benchmarks. | [Speech-to-text API](https://www.gnani.ai/speech-to-text-api) |
| **Timbre v2.5 — Text to Speech (Beta)** | Speaks 10+ Indic languages with context-aware prosody, Indian names, numerals, and lakh/crore cadence; supports WebSocket and SSE streaming. | [Text-to-speech API](https://www.gnani.ai/text-to-speech-api) |
| **Evon v3.3 — Open-weight reasoning model** | 30B-parameter mixture-of-experts model, 128K context and 11 Indian languages natively; Apache 2.0 weights available by request on Hugging Face. | [Evon v3.3 release notes](https://www.gnani.ai/resources/introducing-evon-v3-3-large-language-model) · [Hugging Face model](https://huggingface.co/gnani/gnani-evon-v3.3-30B-A3B) |

The page also has a top banner announcing Prisma v3.0. However, the challenge’s “What You Build On” section names **Prisma v2.5** and **Timbre v2.5**, and the FAQ specifically clarifies that **Evon v3.3 is not on the API platform**. Do not assume that a model mentioned elsewhere on Gnani’s website is available through the challenge credits or API account; check the current API platform and docs.

### Where to build and what is not in scope

- Build on the [Gnani API platform](https://app.gnani.ai/voice), sign in with the registration email, create API keys, and monitor credit usage there.
- The challenge covers the API platform and models hosted on it. The Agent Builder sits outside the challenge scope and has no API keys/API access offered for this challenge, according to the FAQ.
- Evon v3.3 is not available on the API platform yet. Participants may request its weights on Hugging Face and run it themselves; it is not a hosted challenge API endpoint according to the FAQ.
- The page says there is no separate participant workspace/dashboard for managing entries. Project details and the build are shared through the submission form sent by email.

### Build resources linked by the page

- [API dashboard — create keys, test voices and track credit usage](https://app.gnani.ai/voice)
- [Developer documentation](https://docs.gnani.ai/)
- [Quick start — first transcription and synthesis calls](https://docs.gnani.ai/api/introduction/quick-start)
- [Model overview — Prisma, Timbre, Warp and Evon](https://www.gnani.ai/models)
- [Gnani AI Discord support](https://discord.gg/aECcvtABpq)

The page says programme credits and API access instructions arrive by email after registration. For teams, the primary registrant receives the credits.

## 5. Eligibility, teams and internship offers

### Eligibility checklist

A participant must:

1. Be currently enrolled in a degree or course at a college or university in India.
2. Be at least 18 years old on the day of registration.
3. Enter solo or with one teammate who also satisfies the first two conditions.

Teams cannot have more than two participants. A duo registers with one teammate email, and that teammate accepts the terms separately.

### Individual selection

A team submits one project, but internship selection is individual:

- Every shortlisted teammate interviews separately.
- One teammate may receive an offer while the other does not.
- Stipends are paid to each selected intern individually; they are not split between teammates.
- Offers depend on the individual’s assessed skills, interview performance and fit for available roles.
- An internship is confirmed only when Gnani AI issues a written offer.
- Location and working arrangements are confirmed in each written offer.

## 6. Internship shortlist process

The page describes these stages:

1. **Engagement check:** Gnani AI verifies reactions, comments and reshares on nominated public posts, recorded by the closing cutoff.
2. **Eligibility check:** The entry must show genuine use of Gnani AI technology and meet participation conditions.
3. **Shortlisting:** Eligible projects with the strongest verified engagement are shortlisted for interview.
4. **Interviews:** Each shortlisted person interviews individually, including each member of a duo.
5. **Written offers:** Offers and stipend depend on the candidate’s skills, interview performance and role fit.

The page distinguishes award judging from internship shortlisting: category awards are judged on category criteria, while public engagement contributes to internship shortlisting. Organic engagement is required; bought engagement, bots, paid promotion and engagement swaps are prohibited.

## 7. Dates and timeline

| Milestone | Date/details shown |
|---|---|
| Challenge begins | **1 October 2026** — registration opens and build window starts. |
| Final submission deadline | **15 November 2026, 18:00 IST**. |
| After submissions close | Shortlisted participants are interviewed individually. |
| Internship start | Six-month internships are scheduled to begin **1 January 2027**. |

The page gives no interview calendar beyond “after close.”

## 8. All FAQ answers from the page

### Is there a problem statement?
No. The brief is open. Build any working application on Gnani AI models or APIs that addresses a practical need for enterprises, developers or creators.

### Do I need to post my demo before I submit?
Yes. The submission asks for demo post links, so publish first. Nominate one post per platform in the submission. A Gnani AI tag by itself does not complete the entry.

### What can get an entry disqualified?
Purchased engagement, bots, paid promotion, engagement exchanges, plagiarism and misleading demonstrations are prohibited. Invalid interactions may be excluded; substantiated breaches may lead to disqualification.

### How does the stipend work?
Each selected intern receives an individual stipend of up to ₹1 lakh per month. This is the maximum, not a guaranteed fixed amount. The exact stipend is stated in the written offer and is not shared with a teammate.

### If we apply as a team, are we selected together?
No. The team builds and submits one project, but the members interview and are considered for offers separately. One member may be selected without the other. Clearly record each person’s contribution.

### When and how does the internship run?
It runs for six months and is scheduled to start on **1 January 2027**. The offer confirms location and working arrangements.

### Does it cost anything to take part?
The page says each registered participant receives 5,000 programme credits. The programme terms explain what credits cover and how usage is handled; the dashboard shows credit usage. The page does not state that every possible external service or infrastructure cost is covered.

### How is my data handled?
Gnani says it uses registration details to run the programme, assess submissions and contact participants about selection. See the [Gnani AI privacy policy](https://www.gnani.ai/privacy). The page explicitly says not to put real phone numbers, account numbers, Aadhaar, PAN or recorded calls into a project/demo; use synthetic data.

### Can I change my project after registering?
Yes. The title, problem, intended users, models and contributions can be changed until final submission.

### Can I submit more than one entry?
No. Each participant or team may submit one entry.

### Where do I build?
On the [Gnani API platform](https://app.gnani.ai/voice). Use the email registered for the challenge, create API keys and track credit use. Docs and quick starts are at [docs.gnani.ai](https://docs.gnani.ai/).

### I don't have an institutional email, or mine isn't working. What do I do?
The page says access for non-institutional email addresses would open in the second week of October, after which participants could sign in with personal email. Since that date has passed, use the current sign-in flow or contact support if access still fails.

### Can I use the agent builder? Why can't I find API keys for it?
No, it is outside this challenge’s scope. The challenge uses the API platform; the page says API keys are not offered for Agent Builder and credits work on models hosted on the API platform.

### How do I use Evon?
Evon v3.3 is not on the API platform yet. It is open-weight; request the weights from [Hugging Face](https://huggingface.co/gnani/gnani-evon-v3.3-30B-A3B) and run it yourself.

### Is there a participant workspace?
No. Participants describe their project and share their build through the submission form sent by email. The page says there is no dashboard to manage the entry.

### Where do I get help?
Use the [Gnani AI Discord community](https://discord.gg/aECcvtABpq) for build/API questions. The developer docs cover authentication, streaming and code examples.

### Are awards linked to the internship shortlist?
No. Awards are given according to their category criteria, independently of internship selection.

### Can a team or individual win more than one award?
No. A team or individual can win at most one award; each award is worth ₹50,000.

## 9. Rules and practical constraints collected from the page

- Use at least one Gnani AI model or API and name it in the entry.
- Show the actual working application in the public demo video.
- Publish the demo before submitting, then nominate its link(s) in the form.
- Include both required hashtags and tag Gnani AI.
- Submit one entry per participant/team.
- Keep engagement genuine. Do not buy reactions/votes, use bots, pay to promote, exchange engagement, plagiarize or misrepresent the demo.
- For a team entry, identify each member’s real contribution; both members should be ready for separate interviews.
- Do not use real personal, financial or identity data, or real recorded calls, in the project/demo. Use synthetic examples.
- Treat the registration-page terms as authoritative if they differ from this summary.

## 10. Useful links

- [Official challenge page](https://www.gnani.ai/internship)
- [Register to build](https://www.gnani.ai/great-indian-ai-internship-registration-form)
- [Final submission form](https://forms.cloud.microsoft/r/dfFShbp7W7)
- [API dashboard](https://app.gnani.ai/voice)
- [Developer docs](https://docs.gnani.ai/)
- [Quick start](https://docs.gnani.ai/api/introduction/quick-start)
- [Privacy policy](https://www.gnani.ai/privacy)
- [Discord support](https://discord.gg/aECcvtABpq)

## Notes on the earlier project strategy file

This brief captures what the official challenge page itself states. It should be used to correct or qualify any earlier strategy-file claims that imply:

- The challenge page itself makes Prisma v3.0/Timbre v3.0 or voice cloning core API requirements. The challenge section names Prisma v2.5 and Timbre v2.5; the top banner mentions Prisma v3.0 separately.
- Evon v3.3 is available as a hosted API for challenge participants. The FAQ says it is not on the API platform and must be requested and self-hosted.
- Agent Builder is part of this challenge’s API scope. The FAQ explicitly excludes it.
- Internship shortlisting is based only on technical merit. The page says verified engagement informs shortlisting, then individual interviews and candidate fit inform offers.
- A six-figure monthly stipend is guaranteed. The page says “up to” ₹1 lakh and the exact amount is in the written offer.

Technical findings from API documentation, experiments or independent research belong in the strategy/research section and should be labeled separately from these official challenge-page facts.
