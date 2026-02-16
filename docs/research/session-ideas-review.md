# Session Ideas Review — 2026-02-16

> Reviewed against: 6 research docs + 5 open issues (#121, #126, #129, #130, #131)
> Memory system design is handled by a separate subagent — excluded here.

---

## 1. Concrete Proposals (Ready to Become Issues)

### 1.1 Move remaining root .py files to subdirectory packages

- **Title**: `refactor: move db.py, io_utils.py, model_resolution.py, toolset_builder.py, skills.py, skillmaker_tools.py to packages`
- **Problem**: 6 modules still live at root level after the restructuring in #119. Inconsistent layout.
- **Solution**: Move each to its logical package (db → store/, io_utils → util/, model_resolution → agent/, toolset_builder → agent/, skills/skillmaker_tools → skills/). Update all imports.
- **Dependencies**: #119 (file moves) should be merged. #121 (docs update) should follow after.
- **Effort**: Small (half day)
- **Priority**: High — blocks #121 docs pass

### 1.2 Batch/non-interactive mode

- **Title**: `feat: non-interactive batch mode for programmatic agent invocation`
- **Problem**: Autopoiesis is CLI-interactive only. Can't be invoked programmatically for benchmarks, CI, or scripted workflows.
- **Solution**: `autopoiesis run --task "instruction" --output result.json` — accept task as input, produce structured output, auto-approve tools (or use a policy file), exit on completion. No interactive prompts.
- **Dependencies**: None (can land before #126 server)
- **Effort**: 1-2 days
- **Priority**: High — prerequisite for Harbor/Terminal-Bench adapter, CI benchmarks, and the server intake layer

### 1.3 Harbor/Terminal-Bench benchmarking adapter

- **Title**: `feat: Terminal-Bench Harbor adapter for benchmarking`
- **Problem**: No way to measure autopoiesis's capability against standardized benchmarks. Can't track regressions or improvements.
- **Solution**: Write an `AutopoiesisAgent(Agent)` class for Harbor framework. Maps Terminal-Bench's shell interface to autopoiesis's tool system. Run on Terminal-Bench Core (~100 tasks) for baseline.
- **Dependencies**: #1.2 (batch mode)
- **Effort**: 2-3 days
- **Priority**: Medium — important for credibility and optimization, but not blocking user-facing features

### 1.4 Conversation serialization to markdown

- **Title**: `feat: serialize conversations as markdown files with git tracking`
- **Problem**: Conversations live in SQLite/JSONL — opaque, not git-trackable, not human-readable.
- **Solution**: Write sessions as markdown (frontmatter + timestamped messages + tool call annotations). One file per session in `conversations/YYYY/MM/DD/HHMM-slug.md`. Auto-commit on session end. Per the git-memory-system research.
- **Dependencies**: #130 (file-based knowledge — conceptually related, can land independently)
- **Effort**: 2-3 days
- **Priority**: Medium — valuable for auditability and memory provenance, but not blocking core features

### 1.5 Heartbeat system

- **Title**: `feat: periodic heartbeat for proactive agent behavior`
- **Problem**: Agent is purely reactive — only acts when user sends a message. No proactive checking of email, calendar, notifications.
- **Solution**: Timer-based heartbeat (configurable interval, default 30min). Reads `HEARTBEAT.md` for standing tasks. Agent runs a silent turn, messages user only if something needs attention. Suppresses late-night (23:00-08:00) unless urgent.
- **Dependencies**: #126 (FastAPI server — needs persistent process)
- **Effort**: 1-2 days
- **Priority**: High — this is the single biggest jump from "tool" to "assistant"

### 1.6 Telegram channel integration

- **Title**: `feat: Telegram bot channel integration`
- **Problem**: Agent only accessible via CLI. Can't reach it from phone or when away from terminal.
- **Solution**: Telegram bot (grammY or python-telegram-bot) that connects to the FastAPI server. Bidirectional messaging, inline approval buttons, file/image support.
- **Dependencies**: #126 (FastAPI server)
- **Effort**: 3-5 days
- **Priority**: High — first real channel integration, massive usability unlock

---

## 2. Ideas to Discuss Further

### 2.1 PWA frontend (SvelteKit + Svelte 5 workbench)

- **The idea**: Full workbench UI — chat + task cards + file browser + terminal + canvas. SvelteKit + Svelte 5 + shadcn-svelte. Detailed in the UX study and realtime-data-exchange research.
- **Why it's interesting**: The workbench concept (Linear's insight: "chat is a weak form") is the right vision. The research is thorough — stack, protocol, build order are all specified.
- **What's unclear**: Is this premature? The server (#126) doesn't exist yet. Building a frontend before the backend API stabilizes risks rework. Also: who maintains a SvelteKit frontend? It's a significant ongoing commitment.
- **Suggested next step**: Build the FastAPI server first (#126). Use a minimal HTML/JS test client (not SvelteKit) to validate the WebSocket protocol. Only start the PWA after the API is stable and at least one channel (Telegram) is proven. The UX research is excellent reference material — don't lose it, but don't build it yet.

### 2.2 Sub-agent orchestration

- **The idea**: Main agent spawns sub-agents for parallel work. Each runs in isolated context. Results announce back.
- **Why it's interesting**: Enables "research 5 things simultaneously" patterns. OpenClaw study shows this is a key differentiator.
- **What's unclear**: Concurrency model, cost control (each sub-agent burns tokens), context inheritance rules, nesting limits.
- **Suggested next step**: Prototype after #126 (server). Start with simple spawn-and-wait, no nesting. Add orchestration patterns later.

### 2.3 Cron/scheduled tasks

- **The idea**: Standard cron expressions for recurring agent work (daily standup, weekly reports, periodic checks).
- **Why it's interesting**: Combined with heartbeats, enables truly proactive behavior.
- **What's unclear**: How this relates to Topics (#129) — topics already have cron triggers. Is a separate cron system needed, or do topics subsume it?
- **Suggested next step**: Let Topics (#129) handle scheduled triggers. Don't build a separate cron system. If topics prove too heavy for simple recurring tasks, add lightweight cron later.

### 2.4 Context compiler concept

- **The idea**: A system that compiles the agent's context from multiple sources (identity files, active topics, memory, tool descriptions) with a strict budget, prioritization, and freshness tracking.
- **Why it's interesting**: Current context assembly is ad-hoc. A compiler metaphor makes budget enforcement, priority ordering, and staleness detection explicit.
- **What's unclear**: Is this just good engineering of context assembly, or a genuinely new abstraction? The file-based knowledge system (#130) already specifies injection tiers and a 25KB budget.
- **Suggested next step**: Implement the injection tiers from #130 cleanly. If that proves insufficient, extract a "context compiler" as a formal component. Don't over-abstract prematurely.

### 2.5 Memory as a pipeline (replayable, regenerable)

- **The idea**: Memory isn't a store — it's a pipeline. Raw conversations → extraction → distillation → pruning. Each stage is replayable. Delete the distilled output, re-run the pipeline, get it back.
- **Why it's interesting**: Makes memory deterministic and debuggable. If the distillation logic improves, you can re-process all history.
- **What's unclear**: The "replayable" property requires keeping raw conversations forever (storage) and a deterministic extraction process (LLM outputs aren't deterministic). Is the complexity worth it?
- **Suggested next step**: The git-memory-system research already covers this partially (git history = replay). Start with the simpler model: conversations as markdown + periodic distillation. If the need for replay emerges, the raw material (conversation files in git) is already there.

### 2.6 Signal as a channel

- **The idea**: Signal integration alongside Telegram.
- **Why it's interesting**: Signal is more privacy-focused, David may prefer it.
- **What's unclear**: signal-cli is the main integration path — it's unofficial and can break. Maintenance burden vs. Telegram (which has a stable bot API).
- **Suggested next step**: Ship Telegram first. Evaluate Signal demand after using Telegram for a few weeks. The channel abstraction should make adding Signal straightforward if the server API is well-designed.

---

## 3. Ideas to Discard

### 3.1 Output-triggered topic steering

- **The idea**: Topics activate based on the agent's own output (e.g., if the agent mentions "code review," the code-review topic activates).
- **Why discard**: Circular dependency hell. The agent's output depends on active topics, which depend on the agent's output. Hard to debug, hard to predict, adds complexity to the topic system for marginal benefit. Topics should activate from external triggers (webhooks, cron, user command) or explicit agent decision — not implicit pattern matching on output.

### 3.2 Gated activations for topics

- **The idea**: Topics have activation gates — conditions that must be true before a trigger actually activates the topic.
- **Why discard**: Over-engineering. The topic instructions themselves can include conditional logic ("only do X if Y"). Adding a formal gate language is a DSL no one asked for. Keep topics simple: trigger fires → topic activates → instructions tell the agent what to do and when not to.

### 3.3 Text/file-based algorithms (TF-IDF, sentiment analysis, etc.)

- **The idea**: Build custom NLP algorithms (TF-IDF for relevance, sentiment analysis for emotional context) over knowledge files.
- **Why discard**: The LLM *is* the NLP algorithm. Asking Claude to "find relevant files" or "assess sentiment" produces better results than any custom TF-IDF implementation, with zero code to maintain. BM25 in FTS5 already handles keyword relevance. Adding custom NLP is reinventing what the model does natively.

### 3.4 Multi-device session sync

- **The idea**: Multiple devices share a live session — start on desktop, continue on phone, same conversation state synced in real-time.
- **Why discard**: Premature complexity. This is a hard distributed systems problem (conflict resolution, presence, state sync) for a single-user system. The simpler model: each device connects independently to the server. Conversation history is server-side, so any device can see it. Live streaming only goes to the active connection. If true sync is ever needed, the WebSocket protocol from the realtime-data-exchange research supports it — but don't build it until there's actual pain.

### 3.5 Personality/identity files (SOUL.md pattern) as a separate feature

- **The idea**: A standalone feature for personality/identity configuration.
- **Why discard**: This is already fully captured in #130 (file-based knowledge management). SOUL.md, USER.md, AGENTS.md, TOOLS.md are the identity tier, always loaded. There's no separate feature to build — it's part of the knowledge system.

---

## Priority Stack (Top to Bottom)

| # | Item | Blocks | Effort |
|---|------|--------|--------|
| 1 | Move 6 root .py files (#1.1) | #121 docs | Half day |
| 2 | Batch/non-interactive mode (#1.2) | Benchmarking, server | 1-2 days |
| 3 | FastAPI server (#126) — already an issue | Everything else | 1-2 weeks |
| 4 | File-based knowledge (#130) — already an issue | Topics, memory lifecycle | 1 week |
| 5 | Heartbeat system (#1.5) | Proactive behavior | 1-2 days |
| 6 | Telegram integration (#1.6) | Mobile access | 3-5 days |
| 7 | Conversation serialization (#1.4) | Memory provenance | 2-3 days |
| 8 | Terminal-Bench adapter (#1.3) | Benchmarking | 2-3 days |

Items 1-2 have zero dependencies and should ship immediately. Items 3-4 are the foundational issues already tracked. Items 5-8 follow after the server exists.
