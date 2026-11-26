# In-house enterprise coding agents: how changes are verified before merge and after deploy (as of Nov 2026)

Research-method note for the report writer: in this session the page-fetch tool could not reach any primary host (stripe.dev, builders.ramp.com, engineering.atspotify.com, engineering.fb.com, www.infoq.com all failed DNS resolution, which means they are outside the session's allowed network domains). Every finding below therefore comes from web-search result summaries of the linked pages, not from reading the pages in full. Links point at the primary page where the search surfaced it. Items tagged **[secondhand]** come from a newsletter, aggregator or third-party analysis rather than the company itself. Items tagged **[recall, not re-verified]** are details I remember from the primary post but could not re-read this session; treat them as leads to confirm, not as citable facts. Exact quotes should be re-checked against the primary before publication.

## Which verification layers does each organization use beyond agent-written unit tests?

### Takeaway
The publicly described systems lean overwhelmingly on infrastructure that already existed for humans: the same dev environment, the same linters, the same CI suite, the same code review. On top of that, three additions recur: (1) a fast local deterministic loop before CI (Stripe, Spotify, Airbnb, Google), (2) the agent exercising the running app itself, in a browser or staging environment (Ramp, Uber, Coinbase), and (3) an LLM layer that judges the diff or generates adversarial tests (Spotify's judge, Meta's JiTTests, Uber's uReview). Published detail on post-deploy verification (canary, telemetry, auto-rollback) specific to agent changes is nearly absent; Atlassian's vulnerability pipeline is the one clear example of an agent checking the deployed build.

### Cited Findings

**Stripe — Minions** (primary: two stripe.dev posts, Feb 2026)
- Minions run in the same isolated devbox (AWS EC2) that Stripe engineers use, not a special sandbox; isolation means the agent needs no confirmation prompts, and mistakes are confined to one devbox. A devbox is ready, checked out to recent master, in about 10 seconds. — [Stripe, Minions Part 2](https://stripe.dev/blog/minions-stripes-one-shot-end-to-end-coding-agents-part-2); [Stripe, Minions Part 1](https://stripe.dev/blog/minions-stripes-one-shot-end-to-end-coding-agents)
- Validation rests on Stripe's existing test suite of more than three million tests; CI runs a selected subset relevant to the change, not the whole suite. The team "shifts feedback left": linters and other checks run locally before the push to CI. — [Stripe, Minions Part 1](https://stripe.dev/blog/minions-stripes-one-shot-end-to-end-coding-agents); test-count and subset detail via **[secondhand]** [ByteByteGo](https://blog.bytebytego.com/p/how-stripes-minions-ship-1300-prs) and [InfoQ, Mar 2026](https://www.infoq.com/news/2026/03/stripe-autonomous-coding-agents)
- CI is capped: a failed CI run gets one more local fix attempt; autofixes from CI are applied before the agent's second attempt; after the second push and CI run the branch is handed to a human. Third-party write-ups phrase this as "at most two rounds of CI". — [Stripe, Minions Part 2](https://stripe.dev/blog/minions-stripes-one-shot-end-to-end-coding-agents-part-2); phrasing via **[secondhand]** [Victorino, Stripe's Blueprints](https://victorinollc.com/thinking/stripe-minions-blueprints)
- **[secondhand]** Pre-push hooks autofix common issues in under a second and local linters run in under five seconds. — [lilting.ch architecture summary](https://lilting.ch/en/articles/stripe-minions-agent-architecture)
- **[secondhand]** "Blueprints" interleave deterministic nodes (lint, push, filling the PR template) with agentic nodes (implement, fix CI), so that verification steps always run rather than depending on the model choosing to run them. — [Victorino, Stripe's Blueprints](https://victorinollc.com/thinking/stripe-minions-blueprints); [MindStudio](https://www.mindstudio.ai/blog/stripe-minions-blueprint-architecture-deterministic-agentic-nodes)
- The agent loop is a fork of Block's open-source goose. — [Stripe, Minions Part 1](https://stripe.dev/blog/minions-stripes-one-shot-end-to-end-coding-agents)

**Ramp — Inspect** (primary: builders.ramp.com post, Jan 2026; ramp.com product post dated Oct 27, 2026)
- Inspect runs in a sandboxed full-stack environment (Modal Sandboxes; agent core is OpenCode) and is wired into Sentry, Datadog, LaunchDarkly and Temporal specifically so it can verify its own work end to end. — [Ramp Builders, Why We Built Our Own Background Agent](https://builders.ramp.com/post/why-we-built-our-background-agent); [Modal, Feb 2026](https://modal.com/blog/how-ramp-built-a-full-context-background-coding-agent-on-modal)
- Frontend: "it visually verifies its work and gives users screenshots and live previews"; the agent navigates the app in a real browser and takes before-and-after screenshots. — [Ramp Builders](https://builders.ramp.com/post/why-we-built-our-background-agent); [Modal](https://modal.com/blog/how-ramp-built-a-full-context-background-coding-agent-on-modal)
- Backend: it runs the automated test suite, reviews telemetry, and queries feature flags to understand deployment configuration. — [Ramp Builders](https://builders.ramp.com/post/why-we-built-our-background-agent)
- Ramp has published the blueprint so others can build their own; in Oct 2026 Ramp opened early access to Inspect as a product. — [Ramp, Introducing Inspect, Oct 27 2026](https://ramp.com/blog/introducing-inspect); [Ramp support, Inspect overview](https://support.ramp.com/inspect-overview)

**Spotify — background coding agent ("Honk")** (primary: three engineering.atspotify.com posts, Nov–Dec 2025)
- Part 3 (Dec 2025) describes a verification loop of deterministic verifiers plus an LLM judge. "The judge is included in the standard verification loop and runs after all the other verifiers have completed"; it takes the diff of the proposed change and the original prompt and sends them to an LLM for evaluation. — [Spotify Engineering, Honk Part 3](https://engineering.atspotify.com/2025/12/feedback-loops-background-coding-agents-part-3)
- Spotify said it had not yet invested in evals for the judge itself. — [Spotify Engineering, Honk Part 3](https://engineering.atspotify.com/2025/12/feedback-loops-background-coding-agents-part-3)
- **[secondhand, conflicting]** A Medium guide says Spotify revealed at QCon London 2026 that the LLM judge was removed because it was too rigid and blocked correct changes; InfoQ/ZenML summaries say it was dropped as models improved and in-prompt verification steps proved sufficient. A separate later write-up describing Honk running on the Claude Agent SDK in Kubernetes pods (June 2026) does not mention the judge being dropped. No Spotify primary source confirming removal was found. — [Medium guide](https://medium.com/@wasowski.jarek/spotify-honk-fleet-management-ai-coding-system-complete-guide-05cacd6a1d48); [InfoQ, Mar 2026](https://www.infoq.com/news/2026/03/spotify-honk-rewrite); [InfoQ presentation](https://www.infoq.com/presentations/spotify-ai-codebase-migration-agent/)

**Uber — Minion, uReview, AutoCover, Validator**
- **[secondhand]** Minion is Uber's in-house background agent platform; it runs asynchronously on Uber's own CI infrastructure with monorepo access, and "self-validates using Slate environments, an agent browser and staging deploys before a human reviews." — [rywalker.com, Uber AI Coding Agents](https://rywalker.com/research/uber-coding-agents); [Pragmatic Engineer, How Uber uses AI for development](https://newsletter.pragmaticengineer.com/p/how-uber-uses-ai-for-development?open=false)
- uReview, Uber's AI code review system, analyzes over 90% of the roughly 65,000 diffs landed weekly; it measures its own usefulness by re-running five times on the final commit to check whether each posted comment was addressed; on average 65% of comments are addressed in the same changeset. — [Uber Engineering, uReview, Aug 12 2025](https://www.uber.com/blog/ureview/)
- **[secondhand]** AutoCover generates 5,000+ unit tests per month. — [Pragmatic Engineer](https://newsletter.pragmaticengineer.com/p/how-uber-uses-ai-for-development?open=false)

**Meta — ACH mutation testing and Just-in-Time catching tests (JiTTests)**
- ACH (Automated Compliance Hardening) generates mutants representing a class of fault (first privacy), then generates tests that kill them. Its LLM-based equivalent-mutant detector had precision 0.79 / recall 0.47, rising to 0.95 / 0.96 with simple pre-processing. — [arXiv 2501.12862, Mutation-Guided LLM-based Test Generation at Meta](https://arxiv.org/abs/2501.12862); [Engineering at Meta, Sep 30 2025](https://engineering.fb.com/2025/09/30/security/llms-are-the-key-to-mutation-testing-and-better-compliance/)
- JiT catching tests invert the usual contract: they are generated per diff and are meant to fail on the proposed change while passing on the parent revision, surfacing a bug before the code lands. The "dodgy diff" method treats the diff itself as a mutant and generates tests that distinguish it from its parent; failures are harvested as "weak catches". — [arXiv 2601.22832, Just-in-Time Catching Test Generation at Meta](https://arxiv.org/abs/2601.22832)
- False positives are filtered before a human sees anything: an LLM-as-judge ensemble plus a rule-based system (named RubFake in summaries of the Oct 2026 post), with only surviving catches escalated to the diff author. — [Engineering at Meta, Oct 29 2026](https://engineering.fb.com/2026/10/29/security/catching-bugs-before-they-land-jittestings-human-on-the-loop-approach-at-full-scale/); RubFake name via **[secondhand]** [daily.dev summary](https://daily.dev/posts/catching-bugs-before-they-land-jittesting-s-human-on-the-loop-approach-at-full-scale-bvjm0sq9j)
- "Human-on-the-loop": engineers set criteria and review outcomes in aggregate rather than supervising every generated test. — [Engineering at Meta, Oct 29 2026](https://engineering.fb.com/2026/10/29/security/catching-bugs-before-they-land-jittestings-human-on-the-loop-approach-at-full-scale/)

**Google — AI-driven internal migrations**
- Validation is configurable per migration; the two most common checks are that changed files compile and that their unit tests pass. A failed step can trigger an ML-powered repair attempt. Changes then go through normal review by the code owners. — [Google Research blog, Accelerating code migrations with AI](https://research.google/blog/accelerating-code-migrations-with-ai/); [arXiv 2501.06972](https://arxiv.org/pdf/2501.06972)

**Airbnb — LLM-driven test migration (Enzyme to React Testing Library)**
- A per-file state machine ran ordered validation steps (Enzyme refactor, then Jest, then lint, then TypeScript), each with an LLM fix step; on failure the model was given all errors and asked to fix the file. Retrying ("brute force") beat prompt engineering. Prompts grew to 40,000–100,000 tokens with up to 50 related files. — [Airbnb Engineering, Accelerating large-scale test migration with LLMs](https://medium.com/airbnb-engineering/accelerating-large-scale-test-migration-with-llms-9565c208023b)

**Coinbase — Forge (formerly Cloudbot/Claudebot), Mux**
- **[secondhand]** Forge turns a Slack/Linear bug report into a PR: it retrieves repo context, generates code, "validates the changes, and even produces a mobile build for review." — [The New Stack, enterprise agent harness](https://thenewstack.io/enterprise-ai-agent-harness/)
- **[secondhand]** Coinbase runs background review agents that check code for correctness and security while the developer tests the build, an automated security review tool (SAIL), and multi-agent "code review councils". — [ZenML LLMOps database summary](https://www.zenml.io/llmops-database/transforming-product-development-with-ai-first-workflows-and-agent-orchestration)

**Atlassian — Rovo Dev in Agentic Pipelines (vulnerability fixes)**
- After deployment, a "closer" step checks that the matching PR was merged and that the deployed build contains the expected commit, and only then transitions the ticket so the vulnerability scanner can re-verify. This is the clearest published example of an agent workflow confirming the fix in the deployed artifact, with an independent tool (the scanner) as the final oracle. — [Inside Atlassian, vulnerability fixes with Agentic Pipelines](https://www.atlassian.com/blog/bitbucket/vulnerability-fixes-with-agentic-pipelines)

**Shopify — River, Roast**
- **[secondhand]** Roast is an open-source Ruby DSL for structured workflows that combine model calls, local agents, shell commands and iteration; its checks are whatever the workflow author defines. It is not a hosted agent platform. Shopify's internal agent is River. — [The New Stack](https://thenewstack.io/enterprise-ai-agent-harness/)

### Inferences
- The common architecture is "deterministic rails around a model": verification steps are run by the harness, not left to the model's discretion (Stripe blueprints, Spotify's verifier loop, Airbnb's state machine, Google's validate-and-repair). This is the strongest cross-company pattern.
- Layer by layer, as publicly described:

| Layer | Who describes using it |
| --- | --- |
| Existing human-owned CI suite | Stripe, Ramp, Spotify, Uber, Google, Airbnb, Atlassian |
| Fast local lint/format/type loop before CI | Stripe, Spotify, Airbnb |
| Hard cap on CI repair rounds, then human | Stripe (two pushes) |
| Agent drives the running app in a browser | Ramp, Uber (secondhand) |
| Preview / staging / built artifact for the reviewer | Ramp (live previews), Uber (staging deploys, secondhand), Coinbase (mobile build, secondhand) |
| LLM judge on the diff vs. the prompt | Spotify (later reportedly removed), Coinbase review councils (secondhand) |
| AI code review as a separate system | Uber uReview, Coinbase |
| LLM-generated adversarial / mutation tests | Meta (ACH, JiTTests) |
| Telemetry and feature-flag access | Ramp (as agent tools, pre-merge context) |
| Post-deploy confirmation | Atlassian (deployed commit check plus scanner re-verification) |
| Canary / auto-rollback tied to agent changes | none found |

- Ramp's telemetry and feature-flag access is described as context and verification available to the agent during a session, not as an automated post-deploy gate. The public material does not say Inspect watches a rollout.
- Agent changes appear to ride the same deploy pipeline as human changes everywhere; companies describe no agent-specific canary policy, which probably means none exists rather than that it is secret, but this is an inference from silence.

### Gaps
- Could not re-read the primary posts this session (network allowlist). Stripe's exact wording on the CI cap and the test-suite size, and Spotify's list of verifiers, should be confirmed against the primaries.
- **[recall, not re-verified]** Spotify Part 3, as I remember it: verifiers auto-activate from repo contents (for example a build-tool verifier when that tool's manifest is present), are exposed to the agent as a single abstract "verify" tool so the agent need not know the build system, output is parsed down to the relevant errors, and a stop hook runs all verifiers before a PR may be opened; the judge mainly catches scope creep beyond the prompt. Source to confirm: [Honk Part 3](https://engineering.atspotify.com/2025/12/feedback-loops-background-coding-agents-part-3).
- No public description found of canary analysis, production-telemetry gates or automatic rollback applied specifically to agent-authored changes at any of these companies.
- No reliable source found on a LinkedIn in-house background coding agent, on Block's internal Goose verification practices or PR numbers, or on Shopify River's verification and CI setup.
- Meta's Sapienz / end-to-end testing in relation to agent-authored diffs: nothing found from 2025–2026.
- Uber's Validator and "Shepherd" tools are named in summaries of a Pragmatic Engineer episode but not described in anything I could read.

## Do agents write the tests that judge their own work, or rely on pre-existing human-owned suites? How is test weakening prevented?

### Takeaway
The dominant oracle is the pre-existing, human-owned test suite and lint/type toolchain; no company found describes agent-written tests as the thing that decides whether an agent's change is correct. Explicit, published anti-weakening mechanisms are rare: the nearest are Spotify's judge (diff vs. prompt, catching out-of-scope edits), Meta's design in which the generated test is independent of the author and judged against the parent revision, and human review. This is the thinnest part of the public record.

### Cited Findings
- Stripe: validation is the existing three-million-plus test suite plus local linters; the agent's job is to get a CI-passing PR within two pushes, after which a human takes over. — [Stripe, Minions Part 1](https://stripe.dev/blog/minions-stripes-one-shot-end-to-end-coding-agents); [Part 2](https://stripe.dev/blog/minions-stripes-one-shot-end-to-end-coding-agents-part-2)
- Spotify: the judge compares the diff with the original prompt after deterministic verifiers pass, which is a check on what was changed rather than on whether tests pass. — [Spotify Engineering, Honk Part 3](https://engineering.atspotify.com/2025/12/feedback-loops-background-coding-agents-part-3)
- Meta JiTTests: the tests that judge a diff are generated by a separate system, not by the diff's author, and are defined relative to the parent revision (pass on parent, fail on the diff). They are not landed into the codebase as maintained tests; they exist to produce a signal on that one diff. — [arXiv 2601.22832](https://arxiv.org/abs/2601.22832); [arXiv 2504.16472, Harden and Catch](https://arxiv.org/pdf/2504.16472)
- Meta ACH: generated tests are kept only if they kill a mutant the existing suite did not, so a test has to demonstrate fault-detecting power to be accepted; engineers accepted 73% of ACH tests in Messenger and WhatsApp test-a-thons and judged 36% privacy-relevant. — [arXiv 2501.12862](https://arxiv.org/abs/2501.12862)
- Meta's JiT paper used ACH and TestGen-LLM applied to the parent of a diff as baselines, to estimate how often ordinary hardening tests catch a bug by coincidence; change-aware generation produced candidate catches 4x more often than hardening tests and 20x more often than coincidentally failing tests, over 22,126 generated tests. — [arXiv 2601.22832](https://arxiv.org/abs/2601.22832)
- Airbnb: the migrated artifact was the test file itself, so the oracle was that the rewritten test passes Jest, lint and type checks; Airbnb states the migration preserved "the original test intent and code coverage". — [Airbnb Engineering](https://medium.com/airbnb-engineering/accelerating-large-scale-test-migration-with-llms-9565c208023b)
- **[secondhand, unconfirmed]** A third-party guide says a conversion that deletes, skips or weakens a test was rejected even if the file passed; the search could not confirm that Airbnb states this rule. — [BuildBetter summary](https://blog.buildbetter.ai/how-airbnb-used-llms-to-migrate-3500-test-files/)
- Google: validation for migrations is compile plus the existing unit tests of the changed files, followed by owner review. — [Google Research blog](https://research.google/blog/accelerating-code-migrations-with-ai/)
- Uber: AutoCover is a separate test-generation platform (5,000+ unit tests per month) rather than part of Minion's self-check; how its tests are validated was not found. — **[secondhand]** [Pragmatic Engineer](https://newsletter.pragmaticengineer.com/p/how-uber-uses-ai-for-development?open=false)

### Inferences
- Two structural defences against a self-serving oracle appear in the record: (a) separation of author and judge (Meta's JiT generator, Spotify's judge, Uber's uReview, Coinbase's review agents are all distinct from the coding agent), and (b) anchoring to something the author cannot move (the parent revision at Meta; the pre-existing suite at Stripe and Google; a vulnerability scanner at Atlassian).
- Meta's mutation criterion is the only published mechanism that measures whether a test can detect a fault at all, as opposed to whether it passes. Everyone else's defence against a vacuous or weakened test is, as far as published, the human reviewer.
- Spotify's judge is the only described automated check aimed at "the agent changed something it was not asked to change", which is the category test weakening falls into; the reports that it was later removed for over-blocking suggest that an LLM veto on diffs carries a real false-positive cost.
- Airbnb's migration is a caution rather than a model for this question: when the agent's deliverable is the tests, "tests pass" is weak evidence, and Airbnb's stated safeguard is coverage and intent preservation, checked in ways the post does not fully specify.

### Gaps
- No company found publishes a rule such as "the agent may not edit test files", "protected test paths", or "held-out acceptance checks". Whether Stripe, Ramp or Uber restrict agent edits to existing tests is not stated in anything retrieved.
- No published data on how often agents weaken, skip or delete tests in these systems.
- How Ramp's Inspect decides which tests to run, and whether it adds tests of its own, is not described in the retrieved material.
- Whether Meta applies JiTTests specifically or preferentially to agent-authored diffs is not confirmed; one third-party article frames JiTTests as "for agentic code" ([checkops.com](https://checkops.com/blog/meta-jittests-just-in-time-tests)), but I could not verify that framing against Meta's post.

## What human gates remain, and what evidence does the agent attach to the PR?

### Takeaway
Human code review before merge is retained in every well-documented system; the agent's output is a pull request, not a merge. Evidence attached for the reviewer is best documented at Ramp (screenshots, live previews) and by reference at Coinbase (a mobile build) and Uber (staging deploys). The one reported exception to mandatory human review is a third-party claim about Coinbase auto-merging, which is not confirmed by a primary source.

### Cited Findings
- Stripe: minion PRs are "completely minion-produced, human-reviewed, but containing no human-written code." Review by a human is the fixed gate; a second gate is the hand-off to a human operator after the second CI run. — [Stripe, Minions Part 2](https://stripe.dev/blog/minions-stripes-one-shot-end-to-end-coding-agents-part-2)
- **[secondhand]** Stripe's blueprint fills the PR template as a deterministic step. — [Victorino](https://victorinollc.com/thinking/stripe-minions-blueprints)
- Ramp: for frontend work Inspect "gives users screenshots and live previews"; a third-party guide says the before-and-after screenshots are attached to the PR description. — [Ramp Builders](https://builders.ramp.com/post/why-we-built-our-background-agent); attachment detail **[secondhand]** via [Firecrawl, AI software factory](https://www.firecrawl.dev/blog/ai-software-factory)
- Spotify: Honk's output is PRs that owning teams merge ("more than 1,500 pull requests that teams across Spotify have merged"), so the receiving team's review is the gate. — [Spotify Engineering, Honk Part 1, Nov 2025](https://engineering.atspotify.com/2025/11/spotifys-background-coding-agent-part-1)
- Uber: Minion self-validates "before a human reviews"; uReview adds AI review comments on over 90% of diffs ahead of or alongside the human reviewer. — **[secondhand]** [rywalker.com](https://rywalker.com/research/uber-coding-agents); [Uber Engineering, uReview](https://www.uber.com/blog/ureview/)
- Google: AI-generated migration changes are sent to code owners for review like any other change; about 80% of landed changes in the case study were fully AI-authored, the rest human-written or human-edited from AI suggestions. — [arXiv 2501.06972](https://arxiv.org/pdf/2501.06972)
- Meta: JiTTests surface a candidate catch to the diff author, who decides whether it is a real bug; the system's process is "human-on-the-loop" (aggregate oversight) while the individual catch is still a human judgement. — [Engineering at Meta, Oct 29 2026](https://engineering.fb.com/2026/10/29/security/catching-bugs-before-they-land-jittestings-human-on-the-loop-approach-at-full-scale/)
- Coinbase: Forge "produces a mobile build for review." — **[secondhand]** [The New Stack](https://thenewstack.io/enterprise-ai-agent-harness/)
- **[secondhand, unconfirmed, conflicting with the review pattern elsewhere]** One third-party analysis says Forge auto-merges its PRs when tests pass and automated review is positive; a ZenML summary reports "73% more PRs merged without human intervention". Neither was confirmed against a Coinbase primary source. — [rywalker.com, Coinbase Forge](https://rywalker.com/research/coinbase-forge); [ZenML](https://www.zenml.io/llmops-database/transforming-product-development-with-ai-first-workflows-and-agent-orchestration)
- Atlassian: the agentic vulnerability pipeline's stated goal was to make fixes "review-ready"; PRs were merged by humans, then verified in the deployed build. — [Inside Atlassian](https://www.atlassian.com/blog/bitbucket/vulnerability-fixes-with-agentic-pipelines)

### Inferences
- The human gate has moved from "write and check" to "check only", and the companies furthest along (Ramp, Stripe) invest in making that check cheap: a runnable preview or visual proof beats a description of what was done.
- Evidence types that appear in the record: before/after screenshots, a live preview URL, a built mobile artifact, a staging deployment, passing CI status, and AI-review comments. Video recordings and attached test logs are not mentioned in anything retrieved.
- Stripe's two-push cap doubles as an escalation rule: it bounds compute and also guarantees a human sees any change the agent could not get green quickly, rather than letting the agent iterate until something passes.

### Gaps
- **[recall, not re-verified]** Ramp's post, as I remember it, says Inspect opens the PR using the requesting user's GitHub token so that the PR is attributed to that person and they cannot approve their own agent-authored change. Confirm in [Ramp Builders](https://builders.ramp.com/post/why-we-built-our-background-agent).
- What exactly a Stripe minion PR contains beyond the template (test output, a summary of what was verified) is not described in the retrieved material.
- No source states whether any of these companies require a different number or kind of reviewers for agent-authored PRs than for human ones.
- Coinbase's actual merge policy for Forge needs a primary source; the auto-merge claim should not be relied on as stated.

## Quantitative results

### Takeaway
Published numbers are mostly volume and adoption figures (PRs merged, share of PRs), all self-reported and defined inconsistently. Numbers about verification effectiveness are scarce: Spotify's judge veto rate, Stripe's CI cap, Meta's catch statistics, Atlassian's first-run merge rate and Uber's review-comment address rate are the main ones. No company found publishes a defect or incident rate for agent-authored changes compared with human-authored ones.

### Cited Findings

**Volume and share (self-reported; definitions differ)**
- Stripe: over 1,000 fully minion-produced PRs merged per week as of Part 1, over 1,300 as of Part 2 (Feb 2026). — [Stripe, Minions Part 2](https://stripe.dev/blog/minions-stripes-one-shot-end-to-end-coding-agents-part-2)
- Ramp: about 30% of PRs merged to the frontend and backend repos were written by Inspect at the time of the original post (Jan 2026). — [Ramp Builders](https://builders.ramp.com/post/why-we-built-our-background-agent); [InfoQ, Jan 2026](https://www.infoq.com/news/2026/01/ramp-coding-agent-platform/)
- Ramp, later figures: "roughly half" of merged PRs "started by Inspect" (Modal, Feb 2026); about 60% in Jan 2026 and about 75% in May 2026 per a third-party timeline; 75% (and about 90% for Inspect's own repo) per a summary of an Aug 2026 interview; 74% in an Oct 2026 headline. These are **[secondhand]** apart from Modal's, and "started by" may not equal "authored by". — [Modal](https://modal.com/blog/how-ramp-built-a-full-context-background-coding-agent-on-modal); [Port, software factories](https://software-factories.port.io/companies/ramp); [rywalker.com, Ramp Inspect](https://rywalker.com/research/ramp-inspect); [VibeHacker](https://vibehacker.com/news/ramp-opens-early-access-to-inspect-the-multiplayer-cloud-coding-agent-behind-74-); [Pragmatic Engineer](https://newsletter.pragmaticengineer.com/p/why-ramp-built-inspect)
- Spotify: more than 1,500 agent-generated PRs merged into production codebases as of Nov 2025. — [Spotify Engineering, Honk Part 1](https://engineering.atspotify.com/2025/11/spotifys-background-coding-agent-part-1)
- Uber: **[secondhand, two figures]** Minion opened 11% of PRs as of March 2026; an Oct 2026 summary says roughly 15% of production PRs. — [rywalker.com](https://rywalker.com/research/uber-coding-agents); [Dealroom talk summary](https://dealroom.co/news/talk-MDUYSMJmi8A-inside-ubers-software-factory-how-a-decade-of-developer-infrastructure-b/)
- Shopify: **[secondhand]** River participates in one of every eight merged PRs. — [The New Stack](https://thenewstack.io/enterprise-ai-agent-harness/)
- Coinbase: **[secondhand]** Forge produced 5% of merged PRs as of Feb 2026; Mux accounted for 5,068 merged PRs across 461 repos in an April 2026 snapshot, with the caveat that Mux users likely skew toward already-productive AI enthusiasts. A Cursor case study says 75% of all PRs are created by agents of any kind. — [rywalker.com, Coinbase Forge](https://rywalker.com/research/coinbase-forge); [rywalker.com, in-house agents](https://rywalker.com/research/in-house-coding-agents); [Cursor customer story](https://cursor.com/blog/coinbase)
- Google: across 39 migrations over twelve months, 74.45% of code changes and 69.46% of edits were LLM-generated; in the int32-to-int64 case about 80% of landed changes were fully AI-authored; engineers estimated about a 50% reduction in total migration time (an estimate, not a measurement). — [arXiv 2501.06972](https://arxiv.org/pdf/2501.06972); [Google Research blog](https://research.google/blog/accelerating-code-migrations-with-ai/)
- Airbnb: about 3,500 test files migrated in six weeks against an estimated 1.5 years by hand; about 97% completed automatically, the remaining 3% finished manually from the LLM output. — [Airbnb Engineering](https://medium.com/airbnb-engineering/accelerating-large-scale-test-migration-with-llms-9565c208023b)

**Verification effectiveness**
- Spotify: across thousands of agent sessions the LLM judge vetoed about a quarter of them; in about half of the vetoed cases the agent then course-corrected. — [Spotify Engineering, Honk Part 3](https://engineering.atspotify.com/2025/12/feedback-loops-background-coding-agents-part-3)
- Stripe: at most two pushes to CI per run before human hand-off. — [Stripe, Minions Part 2](https://stripe.dev/blog/minions-stripes-one-shot-end-to-end-coding-agents-part-2)
- Meta JiTTests (research paper): 22,126 generated tests; an LLM-as-judge ensemble cut human review load by about 70% in a manual study of 600 diffs with weak catches; of 41 candidate catches reported to engineers, 8 were confirmed true positives, 4 of which would have caused serious failures. — [arXiv 2601.22832](https://arxiv.org/abs/2601.22832); the 41 figure via **[secondhand]** [Goodiebase](https://www.goodiebase.com/news/meta-jittesting-production-human-on-the-loop-2026-10-29)
- Meta JiTTests (production, Oct 29 2026 post): in the first half of 2026 the system caught 74 serious (SEV-level) privacy bugs at the diff stage; privacy SEV occurrence fell about 20% over the period; 589 engineers (64% of those contacted) engaged, reporting a 60% true-positive rate. All self-reported and not independently reproduced. — [Engineering at Meta, Oct 29 2026](https://engineering.fb.com/2026/10/29/security/catching-bugs-before-they-land-jittestings-human-on-the-loop-approach-at-full-scale/); figures as relayed by **[secondhand]** [MarkTechPost, Nov 16 2026](https://www.marktechpost.com/2026/11/16/meta-jittests-llm-catching-tests-privacy-bugs/) and [AlphaSignal](https://alphasignal.ai/news/meta-s-jittests-catches-74-privacy-bugs-before-they-hit-production)
- Meta ACH: engineers accepted 73% of generated tests; 36% judged privacy-relevant. — [arXiv 2501.12862](https://arxiv.org/abs/2501.12862)
- Google: on average more than 75% of AI-generated character changes landed successfully; one source reports about 87% of AI-generated code committed unchanged by the end of the int32-to-int64 migration. — [Google Research blog](https://research.google/blog/accelerating-code-migrations-with-ai/); 87% via **[secondhand]** [The Register, Jan 2025](https://www.theregister.com/2025/01/16/google_ai_code_migration/)
- Atlassian (one team, three months): 120+ vulnerabilities resolved, 55+ agent-created PRs merged, 95% merged on the first run without rework or failed tests. — [Inside Atlassian](https://www.atlassian.com/blog/bitbucket/vulnerability-fixes-with-agentic-pipelines)
- Uber uReview: comments on over 90% of about 65,000 weekly diffs; 65% of comments addressed in the same changeset. — [Uber Engineering, uReview](https://www.uber.com/blog/ureview/)
- Coinbase: **[secondhand]** PR cycle time cut from about 150 hours to about 15. — [rywalker.com, Coinbase Forge](https://rywalker.com/research/coinbase-forge)
- **[secondhand, unconfirmed]** Claims that Spotify's verification loop raised success from roughly 20–30% to about 80% circulate in secondary summaries but were not found in Spotify's own text. — [ZenML summary](https://www.zenml.io/llmops-database/building-reliable-background-coding-agents-with-verification-loops)

### Inferences
- "Share of merged PRs" is not comparable across companies: Stripe counts PRs with no human-written code, Ramp's later figures count PRs "started by" the agent, Shopify counts PRs the agent "participates in", Coinbase's 75% counts any agent. A report should present these side by side only with their definitions.
- The share figures measure adoption and reviewer acceptance, not correctness. A merged PR passed CI and a human reviewer; none of the sources report what happened to it in production.
- Spotify's 25% veto rate is the only published measure of how often an extra LLM check disagrees with a change that already passed deterministic verification; combined with the reports that the judge was later dropped for over-blocking, it suggests a material share of those vetoes may have been false positives, but Spotify published no precision figure.
- Meta's 60% self-reported true-positive rate and the 8-of-41 confirmation rate in the earlier paper show that even a filtered, purpose-built LLM test generator produces a large fraction of false alarms; its value comes from the severity of what the true positives prevent.
- Atlassian's 95% first-run merge rate comes from a narrow, well-specified task class (dependency and vulnerability fixes with a scanner as oracle). Narrow scope with an external oracle is where the best verification numbers appear, as with Google's and Airbnb's migrations.

### Gaps
- No company found publishes incident, revert or defect-escape rates for agent-authored changes versus human-authored ones.
- No published merge rate (opened vs. merged) for Stripe Minions, Ramp Inspect or Uber Minion; only merged counts or shares.
- Stripe's share of total PRs is not confirmed; a "10% of code" figure appears in one third-party headline ([founderland.ai](https://www.founderland.ai/articles/stripes-ai-minions-now-write-10-of-code-inside-the-agent-sys-mlwdrkxj)) and was not verified.
- How often Stripe minions exhaust the two-push cap and get handed to a human is not published in the retrieved material.
- Meta's Oct 2026 figures were read only through search summaries and secondary articles; the primary post should be checked for exact definitions (for example what counts as "caught" and how the 20% SEV reduction is attributed).
