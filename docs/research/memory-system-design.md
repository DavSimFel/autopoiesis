# Autopoiesis Memory System — Definitive Design Document

*The Context Compiler: A file-based, git-versioned, algorithmically-managed knowledge system for AI agents*
*2026-02-16*

---

## Table of Contents

1. [Architecture Overview](#1-architecture-overview)
2. [File Format Specifications](#2-file-format-specifications)
3. [Git Strategy](#3-git-strategy)
4. [Watcher System Design](#4-watcher-system-design)
5. [Gated Activation Protocol](#5-gated-activation-protocol)
6. [Context Compiler Pipeline](#6-context-compiler-pipeline)
7. [Search System](#7-search-system)
8. [Memory Lifecycle](#8-memory-lifecycle)
9. [API Surface](#9-api-surface)
10. [Data Flow Diagrams](#10-data-flow-diagrams)
11. [Implementation Phases](#11-implementation-phases)
12. [Cost Analysis](#12-cost-analysis)

---

## 1. Architecture Overview

### The Core Thesis

The LLM never searches. The system assembles the perfect prompt automatically. 8K of curated context outperforms 200K of uncurated context — cheaper, faster, more accurate.

### Architecture Diagram

```
┌─────────────────────────────────────────────────────────────────────────┐
│                         IMMUTABLE LAYER                                 │
│                   (outside workspace, agent CANNOT edit)                │
│                                                                         │
│   raw/                                                                  │
│   └── conversations/                                                    │
│       └── 2026/02/16/                                                   │
│           ├── 1845-ses_a1b2c3d4-autopoiesis-restructuring.md           │
│           └── 2215-ses_e5f6g7h8-git-memory-research.md                 │
│                                                                         │
│   (append-only, committed immediately, never modified after close)      │
└────────────────────────────┬────────────────────────────────────────────┘
                             │
                    Extraction Algorithms
                    (versionable, tuneable)
                             │
                             ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                         DERIVED LAYER                                   │
│               (inside workspace, agent CAN edit per approval)           │
│                                                                         │
│   knowledge/                                                            │
│   ├── identity/          ← SOUL.md, USER.md, AGENTS.md, TOOLS.md      │
│   ├── memory/            ← MEMORY.md (200-line cap)                    │
│   ├── journal/           ← YYYY-MM-DD.md daily summaries               │
│   ├── projects/          ← per-project context + _active.md            │
│   ├── people/            ← relationship memory + _index.md             │
│   ├── procedures/        ← how-to guides                               │
│   ├── reference/         ← collected research                          │
│   └── archive/           ← stale knowledge (recoverable from git)      │
│                                                                         │
│   topics/                ← reactive situational playbooks               │
│   └── email-triage.md, github-pr-review.md, ...                       │
└────────────────────────────┬────────────────────────────────────────────┘
                             │
                    Index Builder (post-commit hook)
                             │
                             ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                         SEARCH INDEX                                    │
│                   (SQLite FTS5 + sqlite-vec)                           │
│                                                                         │
│   memory.db                                                             │
│   ├── knowledge_fts  (BM25 keyword search)                             │
│   ├── knowledge_vec  (embedding vectors, 1536-dim)                     │
│   └── metadata       (path, category, modified, token_count)           │
│                                                                         │
│   (rebuilt from files, deletable, never source of truth)               │
└────────────────────────────┬────────────────────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                       CONTEXT COMPILER                                  │
│                                                                         │
│   Work item arrives                                                     │
│     → Watchers analyze input + recent output                           │
│       → Pattern match (free)                                           │
│       → Similarity scoring (cheap, local)                              │
│       → Gated activation (LLM yes/no, ~$0.001)                        │
│     → Relevant topics activate                                         │
│     → Subscriptions pull specific context                              │
│     → Algorithms score and rank all available context                  │
│     → Sliding window assembles densest possible prompt                 │
│                                                                         │
│   Budget allocation:                                                    │
│   ┌──────────────────────────────────────────┐                         │
│   │ Identity files        ~17KB  (always)    │                         │
│   │ MEMORY.md             ~3KB   (main sess) │                         │
│   │ Journal (today+yesterday) ~4KB (always)  │                         │
│   │ Active topics         ~2KB   (dynamic)   │                         │
│   │ Topic subscriptions   ~4KB   (dynamic)   │                         │
│   │ ─────────────────────────────────────     │                         │
│   │ Total budget:         ~30KB              │                         │
│   └──────────────────────────────────────────┘                         │
│                                                                         │
│   → Dense prompt → LLM                                                 │
└─────────────────────────────────────────────────────────────────────────┘
```

### Data Flow Summary

```
Conversations (immutable, git-versioned)
  → Extraction algorithms (versionable, tuneable, replayable)
    → Derived knowledge (workspace, agent-editable, git-versioned)
      → Search index (SQLite FTS5 + sqlite-vec, rebuilt from files)
        → Context compiler (sliding window + topics + subscriptions)
          → Dense prompt → LLM
```

Change algorithms → replay over conversations → regenerate knowledge.
A/B test memory strategies on git branches.
Model upgrade → re-extract with better model.

---

## 2. File Format Specifications

### 2.1 Conversation Transcript Format

One markdown file per session. Stored **outside** the workspace in `raw/conversations/`.

**Path pattern**: `raw/conversations/YYYY/MM/DD/HHMM-{session_id}-{slug}.md`

**Example**: `raw/conversations/2026/02/16/1845-ses_a1b2c3d4-autopoiesis-restructuring.md`

```markdown
---
session_id: ses_a1b2c3d4
started: 2026-02-16T18:45:00Z
ended: 2026-02-16T19:32:00Z
model: claude-opus-4.6
channel: webchat
topic: autopoiesis restructuring
tags: [coding, architecture, git]
tokens_in: 45230
tokens_out: 12840
knowledge_changes:
  - path: knowledge/projects/autopoiesis/context.md
    action: updated
    summary: Added migration plan from SQLite to files
  - path: knowledge/journal/2026-02-16.md
    action: appended
    summary: Logged architecture decision
---

# Autopoiesis Restructuring

## 18:45 — user
Read all open issues and give me a summary.

## 18:45 — agent
> [tool:exec] gh issue list --repo autopoiesis --state open → 12 results

Here are all 12 open issues:

1. **#34** — Migrate memory from SQLite to files
2. **#35** — Implement conversation serialization
...

## 18:46 — user
Great analysis. Let's focus on #34 first.

## 18:47 — agent
> [tool:read] knowledge/projects/autopoiesis/context.md

Based on the current architecture, here's my recommendation...

## 18:52 — agent [memory]
> [knowledge:updated] knowledge/projects/autopoiesis/context.md — added migration plan

## 19:30 — user
That's a wrap. Good session.

## 19:32 — agent
> [tool:write] knowledge/journal/2026-02-16.md — appended session summary
```

**Format rules:**
- Frontmatter: session metadata (id, timestamps, model, channel, tags, token counts, knowledge changes)
- Each turn: `## HH:MM — {role}` (role = `user` | `agent` | `system`)
- Tool calls: `> [tool:{name}] {summary} → {brief result}` (one line, no full JSON)
- Memory operations: `## HH:MM — agent [memory]` with `> [knowledge:{action}] {path} — {summary}`
- Binary content: `> [attachment:{path}]` — referenced, never embedded
- Reasoning/thinking: **excluded** — if reasoning led to a decision, the decision goes in knowledge files
- Only input/output. No context state. No sliding window state.

### 2.2 Knowledge File Formats

All knowledge files use markdown with optional YAML frontmatter.

#### Identity Files (`knowledge/identity/`)

```markdown
---
type: identity
role: soul | user | rules | tools
updated: 2026-02-16T18:00:00Z
---

# Soul

I am Silas...
```

**Budget**: ~17KB total across all four identity files. Auto-loaded every turn.

#### Core Memory (`knowledge/memory/MEMORY.md`)

```markdown
---
type: memory
updated: 2026-02-16T18:00:00Z
line_count: 142
---

# Core Memory

## Key Decisions
- 2026-02-14: Switched to file-based memory (from SQLite) — human-readable, git-trackable
- 2026-02-10: Adopted PR-based git workflow for all projects

## Lessons Learned
- Always test webhook payloads with real data, not mocked
- David prefers bullet lists over prose in reports

## Active Context
- Autopoiesis rewrite in progress — file-based memory + topics system
- ExcitingFit launch scheduled for March
```

**Rules:**
- **Hard cap: 200 lines.** Pre-commit hook warns at 180, errors at 220.
- Loaded in main session only (not in shared/group contexts).
- Distilled from daily journals, not a raw dump.
- Every entry has a date prefix for temporal context.

#### Journal Files (`knowledge/journal/YYYY-MM-DD.md`)

```markdown
---
type: journal
date: 2026-02-16
sessions: [ses_a1b2c3d4, ses_e5f6g7h8]
---

## 2026-02-16

### autopoiesis
- Decided file-based memory system architecture
- Key insight: context compiler > traditional retrieval
- Completed research: git memory, file-based knowledge, openclaw agency

### people
- David focused on autopoiesis this week, high energy on architecture decisions

### ops
- Email triage: 3 urgent, 7 actionable, 12 informational
```

**Rules:**
- Auto-load today + yesterday (~4KB budget).
- Bullet points over prose. Group by topic, not time.
- Only write what's worth remembering.
- Archive to `archive/journal/` after 90 days.

#### Project Files (`knowledge/projects/{slug}/`)

```
knowledge/projects/
├── _active.md              # List of active projects (auto-loaded, ~1KB)
├── autopoiesis/
│   ├── context.md          # Architecture, decisions, current state
│   ├── progress.md         # Done, next, blockers
│   └── notes.md            # Accumulated knowledge
└── excitingfit/
    └── ...
```

**`_active.md`** (auto-loaded):
```markdown
---
type: project_index
updated: 2026-02-16
---

# Active Projects

- **autopoiesis** — AI agent framework, file-based memory rewrite in progress
- **excitingfit** — Fitness studio platform, launch March 2026
```

**`context.md`** example:
```markdown
---
type: project_context
project: autopoiesis
updated: 2026-02-16
---

# Autopoiesis — Architecture Context

## Current State
File-based memory system design complete. Implementation starting.

## Key Decisions
- Files as source of truth, SQLite as search index only
- Git for versioning, not just backup
- Topics system for reactive context injection
- Three-tier watcher system for efficient activation

## Stack
- Runtime: TypeScript/Node.js (OpenClaw fork)
- Search: SQLite FTS5 + sqlite-vec
- Storage: Markdown files + git
```

#### People Files (`knowledge/people/`)

```markdown
---
type: person
name: David Feldhofer
relationship: creator/collaborator
updated: 2026-02-16
---

# David Feldhofer

## Communication
- Prefers bullet lists, direct answers
- German native, works in English for technical topics
- High energy on architecture/design discussions

## Context
- Runs Feldhofer Immobilien and ExcitingFit
- Deep interest in AI agent systems
- Drives autopoiesis project direction
```

#### Topic Files (`topics/`)

```markdown
---
type: topic
triggers:
  - type: webhook
    source: email
    event: new_message
  - type: pattern
    match: "email|inbox|mail"
    scope: input
subscriptions:
  - knowledge/procedures/email-workflow.md
  - knowledge/people/_index.md
activation: gated          # auto | gated | manual
priority: high             # low | medium | high | critical
max_context_kb: 4
---

# Email Triage

## Instructions

When a new email arrives:
1. Classify: urgent / actionable / informational / spam
2. If urgent: notify user immediately
3. If actionable: draft a reply, create a task if needed
4. If informational: summarize and file
5. If spam: archive silently

## Context Notes

- Use USER.md for tone and preferences
- Check people/ for relationship context
- Reference email-workflow.md for standard procedures
```

### 2.3 Frontmatter Schema Reference

| Field | Type | Files | Description |
|-------|------|-------|-------------|
| `type` | string | all | File type: `identity`, `memory`, `journal`, `project_context`, `person`, `topic`, `procedure`, `reference` |
| `updated` | ISO datetime | all | Last meaningful update |
| `session_id` | string | conversations | Session identifier |
| `started`/`ended` | ISO datetime | conversations | Session boundaries |
| `model` | string | conversations | LLM model used |
| `channel` | string | conversations | Origin channel |
| `tags` | string[] | conversations, knowledge | Categorization tags |
| `tokens_in`/`tokens_out` | number | conversations | Token usage |
| `knowledge_changes` | object[] | conversations | Files modified during session |
| `triggers` | object[] | topics | Activation triggers |
| `subscriptions` | string[] | topics | Files to inject when active |
| `activation` | enum | topics | `auto`, `gated`, `manual` |
| `priority` | enum | topics | `low`, `medium`, `high`, `critical` |
| `line_count` | number | MEMORY.md | Current line count (for cap enforcement) |

---

## 3. Git Strategy

### 3.1 Repository Structure

Two separate git repos, or a single repo with distinct directories:

```
autopoiesis-memory/
├── .git/
├── .gitignore
├── .gitattributes           # LFS config
├── raw/
│   └── conversations/       # Immutable transcripts
├── knowledge/               # Derived, agent-editable
├── topics/                  # Reactive playbooks
├── attachments/             # Binary files (LFS-tracked)
├── archive/                 # Cold storage
├── scripts/                 # Automation
│   ├── commit.sh
│   ├── rebuild-index.sh
│   ├── archive.sh
│   └── extract.py
├── scratch/                 # .gitignored
└── memory.db                # .gitignored (search index)
```

### 3.2 Commit Strategy

**Two cadences:**

| What | When | Commit Message Format |
|------|------|----------------------|
| Conversations | Immediately on session end | `conversation: {slug}\n\nSession: {path}` |
| Knowledge changes | Every 30 minutes (batched) | `memory: {AI-generated summary}\n\nSession: {path}` |

**Why two cadences:** Conversations are small, append-only, and closing a session is a natural commit point. Knowledge changes accumulate during work and benefit from batching.

**Commit message format:**

```
<type>: <concise summary>

<body — what changed and why>

Session: <conversation path if applicable>
```

**Types:**
- `conversation:` — new transcript saved
- `memory:` — knowledge file updates from interactions
- `identity:` — changes to soul/user/rules/tools
- `maintenance:` — pruning, archiving, reorganization
- `explore:` — exploration branch changes
- `extract:` — algorithmic extraction/re-extraction

**AI-generated commit messages** from the diff:

```python
def generate_commit_message(diff: str) -> str:
    """Use a cheap model (haiku/flash) to summarize the diff."""
    prompt = f"""Summarize this git diff as a commit message.
Format: <type>: <one-line summary>
Then a blank line and 1-2 lines of detail.
Types: memory, conversation, identity, maintenance, explore, extract

Diff:
{diff[:4000]}"""
    return llm_call(prompt, model="haiku", max_tokens=100)
```

### 3.3 Branching Model

```
main                        # Production knowledge state
├── explore/*               # What-if scenarios (auto-created, merge or delete in <7 days)
└── extract/*               # Algorithm testing branches (A/B test memory strategies)
```

**Rules:**
- `main` is the canonical knowledge state — always stable
- No PRs for single-agent use (agent commits directly to main)
- Exploration branches for "what if" scenarios — auto-pruned after 7 days
- `extract/*` branches for testing new extraction algorithms against conversation history
- No long-lived branches

### 3.4 Tag Convention

```
memory/daily/2026-02-16              # Daily snapshot (auto, if changes exist)
memory/weekly/2026-W07               # Weekly snapshot (auto, Sunday 23:59)
memory/milestone/{name}              # Named milestones (manual)
memory/before/{event}                # Pre-event snapshots (manual)
memory/extract/{algorithm-version}   # After extraction algorithm change
```

### 3.5 Git Hooks

**`pre-commit`** — Validate structure:

```bash
#!/bin/bash
set -e

# Validate conversation frontmatter
for f in $(git diff --cached --name-only -- 'raw/conversations/*.md'); do
  if ! head -1 "$f" | grep -q '^---$'; then
    echo "ERROR: $f missing frontmatter"
    exit 1
  fi
done

# Enforce MEMORY.md size cap
if git diff --cached --name-only | grep -q 'knowledge/memory/MEMORY.md'; then
  lines=$(wc -l < knowledge/memory/MEMORY.md)
  if [ "$lines" -gt 220 ]; then
    echo "ERROR: MEMORY.md exceeds 220 lines ($lines). Prune before committing."
    exit 1
  elif [ "$lines" -gt 180 ]; then
    echo "WARNING: MEMORY.md at $lines lines (cap: 200). Consider pruning."
  fi
fi

# Validate topic frontmatter has required fields
for f in $(git diff --cached --name-only -- 'topics/*.md'); do
  if ! grep -q 'triggers:' "$f"; then
    echo "WARNING: $f missing triggers field"
  fi
done
```

**`post-commit`** — Rebuild search index:

```bash
#!/bin/bash
changed=$(git diff --name-only HEAD~1..HEAD -- 'knowledge/' 'raw/conversations/' 'topics/')
if [ -n "$changed" ]; then
  python3 scripts/rebuild-index.py --incremental $changed &
fi
```

### 3.6 Git as Memory Operations

| Memory Operation | Git Command | Example |
|-----------------|-------------|---------|
| When did I learn X? | `git log -S "X" --oneline` | `git log -S "file-based memory" --oneline` |
| Where did this come from? | `git blame {file}` | `git blame knowledge/projects/autopoiesis/context.md` |
| What changed in my understanding? | `git diff {range} -- knowledge/` | `git diff @{1.week.ago}..HEAD -- knowledge/` |
| Snapshot before major change | `git tag memory/before/{event}` | `git tag memory/before/autopoiesis-rewrite` |
| Undo bad knowledge update | `git revert {commit}` | `git revert abc1234` |
| What did I learn today? | `git diff @{yesterday}..HEAD -- knowledge/` | |
| Point-in-time recall | `git show {tag}:{path}` | `git show memory/daily/2026-02-01:knowledge/memory/MEMORY.md` |
| Memory compression | Condense in HEAD, full history in git | Lossy working set, lossless archive |

### 3.7 `.gitignore`

```gitignore
# Search index (rebuilt from files)
memory.db
memory.db-wal
memory.db-shm

# Scratch/ephemeral
scratch/
tmp/
*.tmp

# Secrets
.env
secrets/
*.key
*.pem

# OS
.DS_Store
Thumbs.db
```

### 3.8 `.gitattributes`

```
# LFS for binary attachments
attachments/**/*.png filter=lfs diff=lfs merge=lfs -text
attachments/**/*.jpg filter=lfs diff=lfs merge=lfs -text
attachments/**/*.pdf filter=lfs diff=lfs merge=lfs -text
attachments/**/*.mp4 filter=lfs diff=lfs merge=lfs -text
```

---

## 4. Watcher System Design

### 4.1 Overview

Watchers observe the conversation stream (both input AND output) and trigger topic activation. They form a three-tier filtering pipeline that progressively narrows from cheap/broad to expensive/precise.

```
Conversation stream (every message)
  │
  ├─ Tier 1: Pattern Match (FREE, <1ms)
  │  regex, glob, keyword lists, code detection, language detection
  │  ~80% of messages filtered out here
  │
  ├─ Tier 2: Similarity Scoring (CHEAP, <10ms, local)
  │  TF-IDF, BM25, Jaccard, n-gram fingerprinting
  │  ~90% of remaining filtered out
  │
  └─ Tier 3: Gated Activation (LLM call, ~$0.001, ~200ms)
     Deliberation gate: "Is topic X relevant to this message?"
     Binary yes/no — prevents false positives
     Only fires for candidates that passed Tier 1+2
```

### 4.2 Algorithm Catalog

#### Tier 1: Pattern Match (Free)

| Algorithm | Use Case | Example |
|-----------|----------|---------|
| **Regex match** | Exact patterns in input/output | `/\b(email|inbox|mail)\b/i` → email-triage topic |
| **Glob match** | File path patterns | `*.py` in tool calls → code-review topic |
| **Keyword list** | Domain vocabulary | `["deploy", "production", "rollback"]` → deployment topic |
| **Code detection** | Programming language detection | Fenced code blocks, indentation patterns |
| **Language detection** | Natural language ID | German text → switch to German topic |
| **Mention detection** | @-mention or name patterns | `"David"`, `"@silas"` → people lookup |
| **URL detection** | Link patterns | GitHub URLs → github-pr-review topic |
| **Sentiment shift** | Punctuation/caps patterns | `"!!!"`, `"URGENT"` → escalation topic |

```python
class PatternMatcher:
    """Tier 1: Zero-cost pattern matching against topic triggers."""
    
    def __init__(self, topics: list[Topic]):
        self.rules: list[tuple[re.Pattern, str]] = []
        for topic in topics:
            for trigger in topic.triggers:
                if trigger.type == "pattern":
                    pattern = re.compile(trigger.match, re.IGNORECASE)
                    self.rules.append((pattern, topic.name))
    
    def match(self, text: str) -> set[str]:
        """Returns set of topic names that pattern-matched."""
        candidates = set()
        for pattern, topic_name in self.rules:
            if pattern.search(text):
                candidates.add(topic_name)
        return candidates
```

#### Tier 2: Similarity Scoring (Cheap, Local)

| Algorithm | Cost | Use Case | Implementation |
|-----------|------|----------|---------------|
| **TF-IDF cosine** | ~1ms | Topical similarity to topic description | scikit-learn TfidfVectorizer, pre-computed topic vectors |
| **BM25** | ~1ms | Keyword relevance ranking | rank-bm25 library or custom |
| **Jaccard index** | <1ms | Set overlap of terms | `len(A & B) / len(A \| B)` |
| **N-gram fingerprint** | ~2ms | Fuzzy text matching | Character 3-grams, MinHash for approximate Jaccard |
| **Sentiment analysis** | ~5ms | Emotional context detection | TextBlob or VADER (local, no API) |

```python
class SimilarityScorer:
    """Tier 2: Local similarity scoring against topic profiles."""
    
    def __init__(self, topics: list[Topic]):
        self.vectorizer = TfidfVectorizer(max_features=5000)
        # Pre-compute TF-IDF vectors for each topic's description + instructions
        topic_texts = [t.instructions for t in topics]
        self.topic_matrix = self.vectorizer.fit_transform(topic_texts)
        self.topic_names = [t.name for t in topics]
        self.threshold = 0.15  # Tunable
    
    def score(self, text: str, candidates: set[str] | None = None) -> list[tuple[str, float]]:
        """Score text against topics. Returns [(topic_name, score)] above threshold."""
        text_vec = self.vectorizer.transform([text])
        scores = cosine_similarity(text_vec, self.topic_matrix)[0]
        
        results = []
        for i, (name, score) in enumerate(zip(self.topic_names, scores)):
            if candidates and name not in candidates:
                continue
            if score >= self.threshold:
                results.append((name, float(score)))
        
        return sorted(results, key=lambda x: -x[1])
```

#### Tier 3: Gated Activation (LLM Call)

See [Section 5: Gated Activation Protocol](#5-gated-activation-protocol).

### 4.3 Output-Triggered Steering

**Critical feature:** Watchers observe the agent's own output, not just user input. This enables autonomous self-correction.

```
Agent generates output
  → Output watchers analyze the response
  → If output matches a corrective topic trigger:
    → Topic activates mid-session
    → Corrective instructions injected
    → Agent self-corrects on next turn
```

**Example:** Agent starts writing Python 2 syntax. A code-quality topic has an output watcher for `print ` (without parens). The watcher fires, the topic injects "Use Python 3 syntax", and the agent self-corrects.

```python
class OutputWatcher:
    """Watches agent output for corrective triggers."""
    
    def __init__(self, topics: list[Topic]):
        self.output_patterns: list[tuple[re.Pattern, str, str]] = []
        for topic in topics:
            for trigger in topic.triggers:
                if trigger.scope == "output":
                    pattern = re.compile(trigger.match, re.IGNORECASE)
                    self.output_patterns.append((pattern, topic.name, trigger.correction_hint))
    
    def check(self, agent_output: str) -> list[tuple[str, str]]:
        """Returns [(topic_name, correction_hint)] for triggered patterns."""
        corrections = []
        for pattern, topic_name, hint in self.output_patterns:
            if pattern.search(agent_output):
                corrections.append((topic_name, hint))
        return corrections
```

### 4.4 Watcher Configuration per Topic

Each topic's frontmatter declares its watchers:

```yaml
triggers:
  # Tier 1: Pattern match
  - type: pattern
    match: "email|inbox|mail"
    scope: input              # input | output | both
  
  # Tier 1: Webhook
  - type: webhook
    source: email
    event: new_message
  
  # Tier 1: Cron
  - type: cron
    schedule: "0 8 * * *"    # Daily at 08:00
  
  # Tier 2: Similarity threshold override
  similarity_threshold: 0.2   # Default 0.15
  
  # Tier 3: Gated activation
  activation: gated           # auto (skip gate) | gated (LLM confirmation) | manual (user only)
```

---

## 5. Gated Activation Protocol

### 5.1 Purpose

The gate prevents false positive topic activations. Tier 1 and 2 are heuristic — they'll have false positives. The gate is a cheap LLM call that makes the final decision.

### 5.2 Protocol

```
Candidate topic passes Tier 1 + Tier 2
  │
  ├─ If topic.activation == "auto": activate immediately (skip gate)
  ├─ If topic.activation == "manual": never auto-activate (user only)
  └─ If topic.activation == "gated":
     │
     └─ LLM gate call:
        Model: cheapest available (haiku/flash, ~$0.001/call)
        Max tokens: 1
        Temperature: 0
        
        Prompt:
        "Given this message and topic description, should the topic activate?
         Message: {message_text[:500]}
         Topic: {topic_name} — {topic_description[:200]}
         Answer YES or NO."
        
        → YES: activate topic
        → NO: skip (log for tuning)
```

### 5.3 Implementation

```python
class GatedActivator:
    """Tier 3: LLM-based deliberation gate for topic activation."""
    
    GATE_PROMPT = """Given this message and topic, should the topic activate?

Message: {message}

Topic: {topic_name}
Description: {topic_description}

Answer with exactly one word: YES or NO."""

    def __init__(self, llm_client, model: str = "haiku"):
        self.llm = llm_client
        self.model = model
        self.cache: dict[str, bool] = {}  # LRU cache keyed on (message_hash, topic_name)
    
    async def should_activate(self, message: str, topic: Topic) -> bool:
        """Returns True if the LLM gate approves activation."""
        # Check cache first (same message + topic = same answer)
        cache_key = f"{hash(message[:500])}:{topic.name}"
        if cache_key in self.cache:
            return self.cache[cache_key]
        
        prompt = self.GATE_PROMPT.format(
            message=message[:500],
            topic_name=topic.name,
            topic_description=topic.description[:200]
        )
        
        response = await self.llm.complete(
            model=self.model,
            prompt=prompt,
            max_tokens=1,
            temperature=0
        )
        
        result = response.strip().upper().startswith("YES")
        self.cache[cache_key] = result
        return result
```

### 5.4 Gate Bypass Rules

| Topic Priority | Tier 1 Match | Tier 2 Score | Gate Required? |
|---------------|-------------|-------------|---------------|
| critical | yes | any | **No** — activate immediately |
| high | yes | ≥0.3 | **No** — high confidence, skip gate |
| high | yes | <0.3 | **Yes** |
| medium | yes | ≥0.2 | **Yes** |
| medium | yes | <0.2 | **Drop** — not confident enough |
| low | yes | ≥0.3 | **Yes** |
| low | yes | <0.3 | **Drop** |

### 5.5 Gate Metrics and Tuning

Log every gate decision for offline tuning:

```python
@dataclass
class GateDecision:
    timestamp: datetime
    message_hash: str
    topic_name: str
    tier1_matched: bool
    tier2_score: float
    gate_result: bool      # LLM said YES/NO
    was_useful: bool | None  # Retroactive: did the topic actually help? (filled later)
```

Periodically analyze gate decisions to tune:
- Similarity thresholds (raise if too many false positives)
- Pattern rules (add/remove patterns)
- Gate bypass rules (adjust score thresholds)

---

## 6. Context Compiler Pipeline

### 6.1 Overview

The context compiler assembles the LLM prompt from multiple sources, scored and ranked by relevance, fitting within a token budget.

```
┌─────────────────────────────────────────────────────┐
│                  CONTEXT COMPILER                     │
│                                                       │
│  Inputs:                                              │
│  ├── Current message (user input or trigger payload) │
│  ├── Active topics (from watcher system)             │
│  ├── Session history (sliding window)                │
│  └── Available knowledge (files + index)             │
│                                                       │
│  Pipeline:                                            │
│  1. Reserve fixed slots (identity, rules)            │
│  2. Inject active topic instructions + subscriptions │
│  3. Score remaining knowledge by relevance           │
│  4. Fill remaining budget with highest-scored items  │
│  5. Assemble final prompt                            │
│                                                       │
│  Output:                                              │
│  └── Dense prompt within token budget                │
└─────────────────────────────────────────────────────┘
```

### 6.2 Budget Allocation

For an 8K effective context window (targeting small, fast models):

| Slot | Budget | Priority | Source |
|------|--------|----------|--------|
| System prompt + safety | ~1KB | P0 (fixed) | Runtime |
| Identity files | ~17KB | P0 (fixed) | knowledge/identity/ |
| MEMORY.md | ~3KB | P1 (main session) | knowledge/memory/ |
| Journal (today+yesterday) | ~4KB | P1 (fixed) | knowledge/journal/ |
| Active projects index | ~1KB | P1 (fixed) | knowledge/projects/_active.md |
| Active topic instructions | ~2KB | P2 (dynamic) | topics/ (activated topics) |
| Topic subscriptions | ~4KB | P2 (dynamic) | Files referenced by active topics |
| Scored knowledge | ~remaining | P3 (ranked) | Search results, related files |
| Session history | ~remaining | P4 (sliding) | Recent conversation turns |

**Total budget**: Configurable. Default ~32KB for dense contexts, up to ~100KB for larger models.

### 6.3 Compilation Algorithm

```python
class ContextCompiler:
    """Assembles the densest possible prompt from available context sources."""
    
    def __init__(self, config: CompilerConfig):
        self.token_budget = config.token_budget  # e.g., 8192
        self.tokenizer = config.tokenizer
    
    def compile(
        self,
        message: str,
        active_topics: list[Topic],
        session_history: list[Message],
        available_knowledge: list[KnowledgeFile]
    ) -> str:
        budget = self.token_budget
        sections: list[tuple[int, str, str]] = []  # (priority, label, content)
        
        # ── P0: Fixed slots (always included) ──
        identity = self._load_identity_files()
        budget -= self._count_tokens(identity)
        sections.append((0, "identity", identity))
        
        # ── P1: Session-level context ──
        memory = self._load_file("knowledge/memory/MEMORY.md")
        journal = self._load_journal()
        active_projects = self._load_file("knowledge/projects/_active.md")
        
        for label, content in [("memory", memory), ("journal", journal), ("projects", active_projects)]:
            tokens = self._count_tokens(content)
            if tokens <= budget:
                sections.append((1, label, content))
                budget -= tokens
        
        # ── P2: Active topic context ──
        for topic in sorted(active_topics, key=lambda t: t.priority_score, reverse=True):
            # Inject topic instructions
            instructions = topic.render_instructions()
            tokens = self._count_tokens(instructions)
            if tokens <= budget:
                sections.append((2, f"topic:{topic.name}", instructions))
                budget -= tokens
            
            # Inject topic subscriptions
            for sub_path in topic.subscriptions:
                sub_content = self._load_file(sub_path)
                tokens = self._count_tokens(sub_content)
                if tokens <= budget:
                    sections.append((2, f"sub:{sub_path}", sub_content))
                    budget -= tokens
        
        # ── P3: Scored knowledge (dynamic, relevance-ranked) ──
        scored = self._score_knowledge(message, available_knowledge, active_topics)
        for item in scored:
            tokens = self._count_tokens(item.snippet)
            if tokens <= budget:
                sections.append((3, f"knowledge:{item.path}", item.snippet))
                budget -= tokens
            if budget < 100:
                break
        
        # ── P4: Session history (sliding window, newest first) ──
        for msg in reversed(session_history):
            tokens = self._count_tokens(msg.render())
            if tokens <= budget:
                sections.append((4, f"history:{msg.id}", msg.render()))
                budget -= tokens
            else:
                break  # Can't fit more history
        
        # ── Assemble ──
        return self._assemble(sections)
    
    def _score_knowledge(
        self,
        message: str,
        files: list[KnowledgeFile],
        active_topics: list[Topic]
    ) -> list[ScoredItem]:
        """Score knowledge files by relevance to current message and active topics."""
        scores = []
        
        # Combine message + topic keywords for scoring
        query = message
        for topic in active_topics:
            query += " " + topic.keywords
        
        for f in files:
            # Skip files already included (identity, memory, journal, subscriptions)
            if f.already_included:
                continue
            
            score = 0.0
            # BM25 score
            score += 0.4 * self.search_index.bm25_score(query, f.path)
            # Vector similarity
            score += 0.6 * self.search_index.vector_score(query, f.path)
            # Recency boost (exponential decay, half-life 7 days)
            days_old = (now() - f.modified).days
            score *= math.exp(-0.1 * days_old)
            # Frequency boost (files referenced more often score higher)
            score *= 1.0 + 0.1 * f.reference_count
            
            if score > 0.05:
                scores.append(ScoredItem(path=f.path, score=score, snippet=f.snippet(max_chars=500)))
        
        return sorted(scores, key=lambda s: -s.score)
    
    def _assemble(self, sections: list[tuple[int, str, str]]) -> str:
        """Assemble sections into final prompt, ordered by priority."""
        sections.sort(key=lambda s: s[0])
        parts = []
        for priority, label, content in sections:
            parts.append(f"<!-- {label} -->\n{content}")
        return "\n\n".join(parts)
```

### 6.4 Sliding Window Mechanics

The sliding window is NOT just "drop old messages." It's a compaction system:

```
Full context window:
┌─────────────────────────────────────────┐
│ [System + Identity + Memory]  ~25KB     │  ← Fixed, never dropped
│ [Active Topics + Subs]        ~6KB      │  ← Dynamic, topic-dependent
│ [Scored Knowledge]            ~4KB      │  ← Ranked, variable
│ [Session History]             ~remaining │  ← Sliding, FIFO
└─────────────────────────────────────────┘

When session history grows beyond budget:
1. Oldest messages drop first
2. Before dropping, extract to journal (pre-compaction flush)
3. Tool call results are summarized (full output → one-line summary)
4. System messages and identity are NEVER dropped
```

**Pre-compaction memory flush** (from OpenClaw pattern):
When the context window is near capacity, trigger a silent turn that prompts the model to write durable notes before compaction erases conversation history.

```python
async def pre_compaction_flush(session: Session):
    """Save important context before sliding window drops old messages."""
    prompt = """The context window is filling up. Before older messages are dropped,
    write any important information to the appropriate knowledge files:
    - Decisions → knowledge/projects/{project}/context.md
    - Lessons → knowledge/memory/MEMORY.md
    - Daily events → knowledge/journal/{today}.md
    
    Only write what's worth preserving. If nothing important, reply FLUSH_OK."""
    
    response = await agent_run(session, prompt, silent=True)
    # Agent writes to files, then conversation compacts
```

---

## 7. Search System

### 7.1 Architecture

One function: `search(query)` — hybrid BM25 + vector, searches across knowledge files AND conversation transcripts.

```
search("migration plan")
  │
  ├─ BM25 (SQLite FTS5)
  │  → keyword matches ranked by relevance
  │
  ├─ Vector (sqlite-vec)
  │  → semantic matches by embedding similarity
  │
  └─ Hybrid merge (0.4 × BM25 + 0.6 × vector)
     → deduplicated, ranked results
     → [{path, snippet, score, category}]
```

### 7.2 SQLite Schema

```sql
-- Single SQLite database: memory.db

-- FTS5 full-text search
CREATE VIRTUAL TABLE knowledge_fts USING fts5(
    path,
    content,
    category,           -- 'identity', 'memory', 'journal', 'project', 'person', 'procedure', 'reference', 'conversation', 'topic'
    tokenize='porter unicode61'
);

-- Vector embeddings
CREATE VIRTUAL TABLE knowledge_vec USING vec0(
    path TEXT PRIMARY KEY,
    embedding FLOAT[1536]    -- OpenAI text-embedding-3-small or equivalent
);

-- Metadata
CREATE TABLE knowledge_meta (
    path TEXT PRIMARY KEY,
    category TEXT NOT NULL,
    modified REAL NOT NULL,
    token_count INTEGER,
    line_count INTEGER,
    tags TEXT,               -- JSON array
    last_indexed REAL
);

-- Indexes
CREATE INDEX idx_meta_category ON knowledge_meta(category);
CREATE INDEX idx_meta_modified ON knowledge_meta(modified);
```

### 7.3 Index Building

```python
class SearchIndex:
    """Hybrid BM25 + vector search index over knowledge files."""
    
    def __init__(self, db_path: str, embedding_model: str = "text-embedding-3-small"):
        self.db = sqlite3.connect(db_path)
        self.db.enable_load_extension(True)
        self.db.load_extension("vec0")
        self.embedding_model = embedding_model
        self._ensure_schema()
    
    async def index_file(self, path: str, content: str, category: str):
        """Index a single file (called on file create/modify)."""
        # FTS5
        self.db.execute(
            "INSERT OR REPLACE INTO knowledge_fts(path, content, category) VALUES (?, ?, ?)",
            (path, content, category)
        )
        
        # Embedding (async, non-blocking)
        embedding = await self._embed(content[:8000])  # Truncate for embedding model
        self.db.execute(
            "INSERT OR REPLACE INTO knowledge_vec(path, embedding) VALUES (?, ?)",
            (path, serialize_f32(embedding))
        )
        
        # Metadata
        self.db.execute("""
            INSERT OR REPLACE INTO knowledge_meta(path, category, modified, token_count, line_count, last_indexed)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (path, category, time.time(), count_tokens(content), content.count('\n'), time.time()))
        
        self.db.commit()
    
    def remove_file(self, path: str):
        """Remove a file from the index."""
        self.db.execute("DELETE FROM knowledge_fts WHERE path = ?", (path,))
        self.db.execute("DELETE FROM knowledge_vec WHERE path = ?", (path,))
        self.db.execute("DELETE FROM knowledge_meta WHERE path = ?", (path,))
        self.db.commit()
    
    async def search(self, query: str, limit: int = 10, category: str | None = None) -> list[SearchResult]:
        """Hybrid BM25 + vector search."""
        # BM25 results
        fts_sql = """
            SELECT path, snippet(knowledge_fts, 1, '**', '**', '...', 48), rank
            FROM knowledge_fts WHERE knowledge_fts MATCH ?
        """
        if category:
            fts_sql += f" AND category = '{category}'"
        fts_sql += " ORDER BY rank LIMIT ?"
        fts_results = self.db.execute(fts_sql, (query, limit * 2)).fetchall()
        
        # Vector results
        query_embedding = await self._embed(query)
        vec_results = self.db.execute("""
            SELECT path, distance
            FROM knowledge_vec
            WHERE embedding MATCH ?
            ORDER BY distance LIMIT ?
        """, (serialize_f32(query_embedding), limit * 2)).fetchall()
        
        # Hybrid merge
        scores: dict[str, float] = {}
        
        # Normalize and weight BM25 scores
        if fts_results:
            max_bm25 = max(abs(r[2]) for r in fts_results) or 1
            for path, snippet, rank in fts_results:
                scores[path] = scores.get(path, 0) + 0.4 * (abs(rank) / max_bm25)
        
        # Normalize and weight vector scores (distance → similarity)
        if vec_results:
            max_dist = max(r[1] for r in vec_results) or 1
            for path, distance in vec_results:
                similarity = 1 - (distance / max_dist)
                scores[path] = scores.get(path, 0) + 0.6 * similarity
        
        # Sort and return
        ranked = sorted(scores.items(), key=lambda x: -x[1])[:limit]
        results = []
        for path, score in ranked:
            # Get snippet from FTS results or read file
            snippet = next((r[1] for r in fts_results if r[0] == path), self._read_snippet(path))
            meta = self.db.execute("SELECT category, modified FROM knowledge_meta WHERE path = ?", (path,)).fetchone()
            results.append(SearchResult(path=path, snippet=snippet, score=score, category=meta[0] if meta else "unknown"))
        
        return results
    
    async def rebuild_full(self, knowledge_dir: str, conversations_dir: str):
        """Full index rebuild from files. Safe to run anytime."""
        self.db.execute("DELETE FROM knowledge_fts")
        self.db.execute("DELETE FROM knowledge_vec")
        self.db.execute("DELETE FROM knowledge_meta")
        
        for path in Path(knowledge_dir).rglob("*.md"):
            content = path.read_text()
            category = self._categorize(path)
            await self.index_file(str(path), content, category)
        
        for path in Path(conversations_dir).rglob("*.md"):
            content = path.read_text()
            await self.index_file(str(path), content, "conversation")
        
        self.db.commit()
```

### 7.4 Fallback: ripgrep

When the search index is unavailable or for quick ad-hoc searches:

```python
async def ripgrep_search(query: str, scope: str = "knowledge/") -> list[str]:
    """Fallback search using ripgrep. Fast, no index needed."""
    result = await exec(f"rg -l -i {shlex.quote(query)} {scope}")
    return result.stdout.strip().split('\n') if result.stdout else []
```

The index is an optimization, not a requirement. Delete `memory.db` and ripgrep still works.

---

## 8. Memory Lifecycle

### 8.1 Pipeline Overview

```
  ┌──────────┐     ┌──────────┐     ┌──────────┐     ┌──────────┐     ┌──────────┐     ┌──────────────┐
  │ CAPTURE  │ ──> │ EXTRACT  │ ──> │ CONDENSE │ ──> │  PRUNE   │ ──> │ ARCHIVE  │     │ RECONSTRUCT  │
  │          │     │          │     │          │     │          │     │          │     │              │
  │ Raw conv │     │ Algs →   │     │ Journal  │     │ LRU evict│     │ Stale →  │     │ New algo →   │
  │ → file   │     │ knowledge│     │ → weekly │     │ exp decay│     │ archive/ │     │ replay all   │
  │          │     │ files    │     │ → MEMORY │     │ 200-line │     │          │     │ conversations│
  │ Auto     │     │ Config.  │     │ Scheduled│     │ Scheduled│     │ Scheduled│     │ On-demand    │
  └──────────┘     └──────────┘     └──────────┘     └──────────┘     └──────────┘     └──────────────┘
```

### 8.2 Capture

**Trigger:** Automatic on every conversation session.

```python
class ConversationCapture:
    """Captures raw conversation to immutable transcript file."""
    
    async def on_session_start(self, session: Session):
        """Create transcript file with frontmatter."""
        slug = await self._generate_slug(session)  # From first few messages
        path = f"raw/conversations/{session.started.strftime('%Y/%m/%d')}/{session.started.strftime('%H%M')}-{session.id}-{slug}.md"
        
        frontmatter = {
            "session_id": session.id,
            "started": session.started.isoformat(),
            "model": session.model,
            "channel": session.channel,
            "tags": [],
        }
        
        await write_file(path, f"---\n{yaml.dump(frontmatter)}---\n\n# {slug.replace('-', ' ').title()}\n")
        session.transcript_path = path
    
    async def on_message(self, session: Session, role: str, content: str, meta: dict | None = None):
        """Append message to transcript."""
        timestamp = datetime.now().strftime("%H:%M")
        suffix = f" [{meta['type']}]" if meta and 'type' in meta else ""
        entry = f"\n## {timestamp} — {role}{suffix}\n{content}\n"
        await append_file(session.transcript_path, entry)
    
    async def on_tool_call(self, session: Session, tool: str, args_summary: str, result_summary: str):
        """Append abbreviated tool call."""
        await append_file(session.transcript_path, f"> [tool:{tool}] {args_summary} → {result_summary}\n")
    
    async def on_session_end(self, session: Session):
        """Finalize frontmatter and commit."""
        # Update frontmatter with end time, token counts, knowledge changes, tags
        await self._update_frontmatter(session)
        # Commit immediately
        await exec(f"git add {session.transcript_path} && git commit -m 'conversation: {session.slug}'")
```

### 8.3 Extract

**Trigger:** Configurable — after each session, hourly, or on-demand.

Extraction algorithms process conversation transcripts and update knowledge files.

```python
class KnowledgeExtractor:
    """Extracts structured knowledge from conversation transcripts."""
    
    # Extractors are registered and versioned
    EXTRACTORS = {
        "decisions": DecisionExtractor,      # Finds decisions, writes to project context
        "lessons": LessonExtractor,          # Finds lessons learned, writes to MEMORY.md
        "people": PeopleExtractor,           # Finds people info, writes to people/
        "procedures": ProcedureExtractor,    # Finds how-to info, writes to procedures/
        "facts": FactExtractor,              # Finds factual info, writes to reference/
        "journal": JournalExtractor,         # Summarizes session, writes to journal/
    }
    
    async def extract_from_session(self, transcript_path: str, extractors: list[str] | None = None):
        """Run extraction algorithms on a conversation transcript."""
        content = await read_file(transcript_path)
        active_extractors = extractors or list(self.EXTRACTORS.keys())
        
        for name in active_extractors:
            extractor = self.EXTRACTORS[name]()
            changes = await extractor.extract(content)
            for change in changes:
                await self._apply_change(change)
    
    async def replay_all(self, extractor_names: list[str] | None = None):
        """Replay ALL conversations through extraction algorithms.
        Used when: algorithm changes, model upgrades, knowledge reconstruction."""
        transcripts = sorted(glob("raw/conversations/**/*.md", recursive=True))
        for path in transcripts:
            await self.extract_from_session(path, extractor_names)


class DecisionExtractor:
    """Extracts decisions from conversations."""
    
    async def extract(self, transcript: str) -> list[KnowledgeChange]:
        prompt = """Extract any decisions made in this conversation.
For each decision, output:
- decision: what was decided
- context: why
- project: which project (or "general")

Output JSON array. If no decisions, output [].

Transcript:
{transcript}"""
        
        response = await llm_call(prompt.format(transcript=transcript[:6000]), model="haiku", max_tokens=500)
        decisions = json.loads(response)
        
        changes = []
        for d in decisions:
            project = d.get("project", "general")
            if project != "general":
                path = f"knowledge/projects/{slugify(project)}/context.md"
                content = f"- {datetime.now().strftime('%Y-%m-%d')}: {d['decision']}"
                if d.get("context"):
                    content += f" — {d['context']}"
                changes.append(KnowledgeChange(path=path, action="append", section="Key Decisions", content=content))
        
        return changes
```

### 8.4 Condense

**Trigger:** Scheduled — daily summary, weekly rollup, monthly distillation.

```python
class MemoryCondenser:
    """Condenses episodic memory into curated long-term memory."""
    
    async def daily_summary(self):
        """End-of-day: ensure journal entry exists and is complete."""
        today = date.today().isoformat()
        journal_path = f"knowledge/journal/{today}.md"
        
        # Get today's transcripts
        transcripts = glob(f"raw/conversations/{today.replace('-', '/')}/*.md")
        if not transcripts:
            return  # Nothing happened today
        
        # Generate/update journal entry
        prompt = f"""Summarize today's conversations into a daily journal entry.
Group by topic, use bullet points. Only include what's worth remembering.

Transcripts:
{self._load_transcripts(transcripts, max_chars=8000)}

Existing journal (update, don't duplicate):
{await read_file(journal_path) if exists(journal_path) else "(empty)"}"""
        
        summary = await llm_call(prompt, model="sonnet", max_tokens=500)
        await write_file(journal_path, self._format_journal(today, summary))
    
    async def weekly_rollup(self):
        """Weekly: distill journal entries into MEMORY.md updates."""
        # Read this week's journals
        journals = self._get_week_journals()
        if not journals:
            return
        
        memory = await read_file("knowledge/memory/MEMORY.md")
        
        prompt = f"""Review this week's journal entries and update MEMORY.md.
Add significant insights, decisions, and lessons. Remove stale entries.
Keep under 200 lines total. Be ruthless about what's worth keeping.

This week's journals:
{journals}

Current MEMORY.md:
{memory}

Output the complete updated MEMORY.md content."""
        
        updated = await llm_call(prompt, model="sonnet", max_tokens=2000)
        await write_file("knowledge/memory/MEMORY.md", updated)
    
    async def monthly_distillation(self):
        """Monthly: deep review and cleanup of all knowledge files."""
        # Archive old journals
        await self._archive_old_journals(days=90)
        # Review and prune project files
        await self._review_projects()
        # Review people files
        await self._review_people()
        # Ensure MEMORY.md is under 200 lines
        await self._enforce_memory_cap()
```

### 8.5 Prune

**Trigger:** Scheduled + pre-commit hook.

```python
class MemoryPruner:
    """Enforces size caps and removes stale knowledge."""
    
    MEMORY_LINE_CAP = 200
    JOURNAL_RETENTION_DAYS = 90
    
    async def prune_memory(self):
        """Enforce MEMORY.md line cap."""
        content = await read_file("knowledge/memory/MEMORY.md")
        lines = content.split('\n')
        
        if len(lines) <= self.MEMORY_LINE_CAP:
            return
        
        prompt = f"""MEMORY.md has {len(lines)} lines (cap: {self.MEMORY_LINE_CAP}).
Reduce to under {self.MEMORY_LINE_CAP} lines by:
1. Removing entries captured in more specific files (project notes, people files)
2. Merging redundant entries
3. Removing stale/superseded information
4. Archiving historically valuable but not operationally relevant items

Current content:
{content}

Output the pruned MEMORY.md content."""
        
        pruned = await llm_call(prompt, model="sonnet", max_tokens=2000)
        await write_file("knowledge/memory/MEMORY.md", pruned)
    
    async def prune_journals(self):
        """Archive journal entries older than retention period."""
        cutoff = date.today() - timedelta(days=self.JOURNAL_RETENTION_DAYS)
        for path in glob("knowledge/journal/*.md"):
            file_date = date.fromisoformat(Path(path).stem)
            if file_date < cutoff:
                archive_path = path.replace("knowledge/journal/", "archive/journal/")
                await move_file(path, archive_path)
    
    async def score_and_evict(self):
        """LRU + exponential decay eviction for knowledge files."""
        files = await self._list_knowledge_files()
        
        for f in files:
            # Score = recency × frequency × relevance
            days_old = (date.today() - f.modified.date()).days
            decay = math.exp(-0.05 * days_old)  # Half-life ~14 days
            score = decay * f.reference_count
            
            if score < 0.01 and days_old > 30:
                # Candidate for archival
                archive_path = f.path.replace("knowledge/", "archive/")
                await move_file(f.path, archive_path)
```

### 8.6 Archive

**Trigger:** Scheduled (monthly) + on-demand.

```
knowledge/          → Active knowledge (hot)
archive/            → Cold storage (searchable but not auto-loaded)
git history         → Lossless archive (everything ever known)
```

Archive is a git-tracked directory. Nothing is truly deleted — `archive/` preserves files that might be needed again, and `git log` preserves the complete history of every file that ever existed.

### 8.7 Reconstruct

**Trigger:** On-demand — when algorithms change, models upgrade, or knowledge needs regeneration.

```python
async def reconstruct_knowledge(
    extractors: list[str] | None = None,
    model: str | None = None,
    branch: str | None = None
):
    """Replay all conversations through extraction algorithms to regenerate knowledge.
    
    Use cases:
    - Algorithm change: new/improved extraction logic
    - Model upgrade: better model produces better extractions
    - A/B testing: compare extraction strategies on branches
    """
    if branch:
        await exec(f"git checkout -b extract/{branch}")
    
    # Clear derived knowledge (but keep identity files)
    for dir in ["memory", "journal", "projects", "people", "procedures", "reference"]:
        await exec(f"rm -rf knowledge/{dir}/*")
    
    # Replay all conversations
    extractor = KnowledgeExtractor()
    if model:
        extractor.default_model = model
    await extractor.replay_all(extractors)
    
    # Run condensation
    condenser = MemoryCondenser()
    await condenser.weekly_rollup()
    
    if branch:
        await exec(f"git add -A && git commit -m 'extract: regenerated knowledge with {branch}'")
        # Compare with main
        diff = await exec(f"git diff main..HEAD --stat -- knowledge/")
        return diff
```

---

## 9. API Surface

### 9.1 Runtime API (Tools the Agent Calls)

```python
# ── Search ──
async def search(query: str, limit: int = 10, category: str | None = None) -> list[SearchResult]:
    """Unified hybrid search across all knowledge and conversations.
    
    Args:
        query: Natural language search query
        limit: Max results (default 10)
        category: Filter by category (identity, memory, journal, project, person, procedure, reference, conversation, topic)
    
    Returns:
        List of {path, snippet, score, category}
    """

# ── Standard file tools (already exist in OpenClaw) ──
async def read(path: str, offset: int = 0, limit: int | None = None) -> str
async def write(path: str, content: str) -> None
async def edit(path: str, old_text: str, new_text: str) -> None

# ── Git introspection (via exec) ──
# git log -S "query" --oneline
# git blame path
# git diff range -- knowledge/
# git show tag:path
```

### 9.2 Runtime API (System Calls — Not Agent-Facing)

```python
# ── Conversation Persistence ──
class ConversationCapture:
    async def on_session_start(session: Session) -> None
    async def on_message(session: Session, role: str, content: str, meta: dict | None) -> None
    async def on_tool_call(session: Session, tool: str, args_summary: str, result_summary: str) -> None
    async def on_session_end(session: Session) -> None

# ── Context Compiler ──
class ContextCompiler:
    def compile(message: str, active_topics: list[Topic], session_history: list[Message], available_knowledge: list[KnowledgeFile]) -> str

# ── Watcher System ──
class WatcherPipeline:
    def process(message: str, direction: Literal["input", "output"]) -> list[TopicActivation]

class PatternMatcher:
    def match(text: str) -> set[str]  # topic names

class SimilarityScorer:
    def score(text: str, candidates: set[str] | None) -> list[tuple[str, float]]

class GatedActivator:
    async def should_activate(message: str, topic: Topic) -> bool

# ── Search Index ──
class SearchIndex:
    async def index_file(path: str, content: str, category: str) -> None
    def remove_file(path: str) -> None
    async def search(query: str, limit: int, category: str | None) -> list[SearchResult]
    async def rebuild_full(knowledge_dir: str, conversations_dir: str) -> None

# ── Memory Lifecycle ──
class KnowledgeExtractor:
    async def extract_from_session(transcript_path: str, extractors: list[str] | None) -> None
    async def replay_all(extractor_names: list[str] | None) -> None

class MemoryCondenser:
    async def daily_summary() -> None
    async def weekly_rollup() -> None
    async def monthly_distillation() -> None

class MemoryPruner:
    async def prune_memory() -> None
    async def prune_journals() -> None
    async def score_and_evict() -> None

# ── Git Operations ──
class MemoryGit:
    async def batch_commit(message: str | None = None) -> None  # Auto-generates if None
    async def tag_daily() -> None
    async def tag_milestone(name: str, message: str) -> None
    async def push() -> None
```

### 9.3 Configuration

```yaml
# memory-config.yaml

context_compiler:
  token_budget: 8192                    # Target context size
  identity_budget_kb: 17
  memory_budget_kb: 3
  journal_budget_kb: 4
  topic_budget_kb: 6
  
search:
  bm25_weight: 0.4
  vector_weight: 0.6
  embedding_model: text-embedding-3-small
  embedding_dimensions: 1536
  
watchers:
  similarity_threshold: 0.15
  gate_model: haiku
  gate_max_tokens: 1
  
lifecycle:
  commit_interval_minutes: 30
  journal_retention_days: 90
  memory_line_cap: 200
  extraction_trigger: on_session_end     # on_session_end | hourly | manual
  condensation_schedule: "0 23 * * *"    # Daily at 23:00
  pruning_schedule: "0 0 * * 0"          # Weekly Sunday midnight
  
git:
  auto_commit: true
  auto_push: true
  auto_tag_daily: true
  commit_message_model: haiku
```

---

## 10. Data Flow Diagrams

### 10.1 New Conversation

```
User sends message
  │
  ├─ ConversationCapture.on_session_start()
  │  └─ Creates: raw/conversations/2026/02/16/1845-ses_abc-topic.md
  │
  ├─ ConversationCapture.on_message(role="user", content=...)
  │  └─ Appends: ## 18:45 — user\n{content}
  │
  ├─ WatcherPipeline.process(message, direction="input")
  │  ├─ PatternMatcher.match() → candidates: {"email-triage"}
  │  ├─ SimilarityScorer.score() → [("email-triage", 0.31)]
  │  └─ GatedActivator.should_activate() → YES
  │     └─ Topic "email-triage" activated
  │
  ├─ ContextCompiler.compile()
  │  ├─ P0: identity files (17KB)
  │  ├─ P1: MEMORY.md + journal + _active.md (8KB)
  │  ├─ P2: email-triage instructions + subscriptions (4KB)
  │  ├─ P3: scored knowledge (2KB)
  │  └─ P4: session history (remaining)
  │  └─ → Dense prompt (~32KB)
  │
  ├─ LLM generates response
  │  ├─ ConversationCapture.on_message(role="agent", content=...)
  │  ├─ WatcherPipeline.process(response, direction="output")
  │  │  └─ (check for corrective triggers)
  │  └─ ConversationCapture.on_tool_call(...) if tools used
  │
  ├─ Session ends
  │  ├─ ConversationCapture.on_session_end()
  │  │  └─ Finalizes frontmatter (end time, tokens, knowledge_changes)
  │  ├─ git add + git commit (immediate for conversation)
  │  └─ KnowledgeExtractor.extract_from_session() (if configured)
  │
  └─ 30-minute batch commit (if knowledge files changed)
     └─ git add knowledge/ && git commit -m "memory: ..."
```

### 10.2 Topic Activation

```
Message: "Can you review the PR that just came in?"
  │
  ├─ Tier 1: PatternMatcher
  │  Patterns checked:
  │  - "PR|pull request|review" → matches github-pr-review topic ✓
  │  - "email|inbox" → no match ✗
  │  Candidates: {"github-pr-review"}
  │
  ├─ Tier 2: SimilarityScorer
  │  TF-IDF cosine(message, github-pr-review.instructions) = 0.28 (> 0.15 threshold) ✓
  │  Score passes.
  │
  ├─ Tier 3: GatedActivator (topic.activation == "gated")
  │  Prompt: "Should 'github-pr-review' activate for 'Can you review the PR...'?"
  │  LLM response: "YES"
  │
  └─ Activation:
     ├─ Load topic instructions (topics/github-pr-review.md)
     ├─ Load subscriptions:
     │  - knowledge/procedures/code-review.md
     │  - knowledge/projects/_active.md (already loaded)
     └─ Inject into context compiler at P2 priority
```

### 10.3 Memory Condensation

```
Cron: Daily at 23:00
  │
  ├─ MemoryCondenser.daily_summary()
  │  ├─ Load today's transcripts from raw/conversations/2026/02/16/*.md
  │  ├─ LLM: "Summarize into journal entry" (sonnet, ~500 tokens out)
  │  └─ Write: knowledge/journal/2026-02-16.md
  │
  ├─ If Sunday:
  │  └─ MemoryCondenser.weekly_rollup()
  │     ├─ Load this week's journal entries
  │     ├─ Load current MEMORY.md
  │     ├─ LLM: "Update MEMORY.md with this week's insights" (sonnet, ~2000 tokens out)
  │     └─ Write: knowledge/memory/MEMORY.md
  │
  ├─ MemoryPruner.prune_memory()
  │  └─ If MEMORY.md > 200 lines: LLM prune (sonnet, ~2000 tokens)
  │
  ├─ MemoryPruner.prune_journals()
  │  └─ Move journals > 90 days to archive/journal/
  │
  └─ git add -A && git commit -m "maintenance: daily condensation"
```

### 10.4 Knowledge Reconstruction

```
Developer changes extraction algorithm
  │
  ├─ git checkout -b extract/v2-decisions
  │
  ├─ Clear derived knowledge:
  │  rm -rf knowledge/{memory,journal,projects,people,procedures,reference}/*
  │
  ├─ KnowledgeExtractor.replay_all(extractors=["decisions"])
  │  ├─ For each transcript in raw/conversations/**/*.md (chronological):
  │  │  └─ DecisionExtractor.extract(transcript) → KnowledgeChanges
  │  │     └─ Apply changes to knowledge files
  │  └─ (processes all historical conversations)
  │
  ├─ MemoryCondenser.weekly_rollup() (rebuild MEMORY.md)
  │
  ├─ git add -A && git commit -m "extract: v2 decision extractor"
  │
  ├─ Compare with main:
  │  git diff main..HEAD --stat -- knowledge/
  │  # Shows what changed with new algorithm
  │
  └─ If satisfied:
     git checkout main && git merge extract/v2-decisions
     git branch -d extract/v2-decisions
```

---

## 11. Implementation Phases

### Phase 1: Foundation (Week 1-2)

**Goal:** Conversation persistence + basic knowledge structure + git automation.

| Task | Priority | Effort |
|------|----------|--------|
| Conversation serializer (capture input/output/tools to markdown) | P0 | 2 days |
| Directory structure setup (knowledge/, topics/, raw/) | P0 | 0.5 day |
| Auto-commit on session end | P0 | 1 day |
| 30-minute batch commit for knowledge changes | P0 | 0.5 day |
| Pre-commit hook (frontmatter validation, MEMORY.md cap) | P1 | 0.5 day |
| Identity file injection (SOUL.md, USER.md, AGENTS.md, TOOLS.md) | P0 | 1 day |
| Journal system (daily notes) | P1 | 1 day |
| Basic `search()` via ripgrep wrapper | P1 | 0.5 day |
| Git introspection tools (`git log -S`, `git blame`, `git diff`) | P2 | 0.5 day |

**Deliverable:** Agent writes conversations to files, commits automatically, knowledge directory exists, ripgrep search works.

### Phase 2: Intelligence (Week 3-5)

**Goal:** Context compiler + watcher system + search index.

| Task | Priority | Effort |
|------|----------|--------|
| Context compiler (budget allocation, priority slots, assembly) | P0 | 3 days |
| Topic file format + loader | P0 | 1 day |
| Tier 1: Pattern matcher | P0 | 1 day |
| Tier 2: TF-IDF similarity scorer | P1 | 1 day |
| Tier 3: Gated activator (LLM yes/no) | P1 | 1 day |
| SQLite FTS5 index + post-commit rebuild | P1 | 2 days |
| sqlite-vec embedding index | P2 | 2 days |
| Hybrid search merge (BM25 + vector) | P2 | 1 day |
| Output-triggered steering (watchers on agent output) | P2 | 1 day |
| Pre-compaction memory flush | P1 | 1 day |

**Deliverable:** Context compiler assembles prompts from topics + subscriptions + scored knowledge. Watchers detect topic relevance. Hybrid search works.

### Phase 3: Lifecycle (Week 6-8)

**Goal:** Memory lifecycle automation + extraction + condensation.

| Task | Priority | Effort |
|------|----------|--------|
| Knowledge extractor framework (pluggable extractors) | P0 | 2 days |
| Decision extractor | P1 | 1 day |
| Journal extractor (daily summary) | P1 | 1 day |
| Lesson extractor | P2 | 1 day |
| People extractor | P2 | 1 day |
| Daily condensation (cron) | P1 | 1 day |
| Weekly rollup (MEMORY.md update) | P1 | 1 day |
| Memory pruner (line cap, LRU eviction) | P1 | 1 day |
| Journal archiver (90-day retention) | P2 | 0.5 day |
| AI-generated commit messages | P2 | 1 day |
| Daily/weekly git tags | P2 | 0.5 day |

**Deliverable:** Full memory lifecycle runs automatically. Knowledge is extracted, condensed, pruned, and archived.

### Phase 4: Advanced (Week 9+)

| Task | Priority | Effort |
|------|----------|--------|
| Knowledge reconstruction (replay conversations) | P1 | 2 days |
| A/B testing on extract branches | P2 | 1 day |
| Gate decision logging + offline tuning | P2 | 1 day |
| Git-crypt for private knowledge | P3 | 1 day |
| Multi-agent shared knowledge (submodules) | P3 | 2 days |
| Sparse checkout for sub-agents | P3 | 1 day |
| Wikilinks between files | P3 | 1 day |

---

## 12. Cost Analysis

### 12.1 Per-Interaction Costs

| Operation | Model | Tokens In | Tokens Out | Cost per Call | Frequency |
|-----------|-------|-----------|------------|---------------|-----------|
| Gate activation (Tier 3) | Haiku | ~200 | 1 | ~$0.0002 | 0-3 per message |
| Commit message generation | Haiku | ~1000 | 50 | ~$0.0003 | Every 30 min |
| Pre-compaction flush | Sonnet | ~2000 | 500 | ~$0.005 | Every 2-4 hours |

### 12.2 Scheduled Costs (Daily)

| Operation | Model | Tokens In | Tokens Out | Cost | Frequency |
|-----------|-------|-----------|------------|------|-----------|
| Daily journal summary | Sonnet | ~4000 | 500 | ~$0.008 | Daily |
| Weekly MEMORY.md rollup | Sonnet | ~6000 | 2000 | ~$0.02 | Weekly |
| Monthly distillation | Sonnet | ~10000 | 3000 | ~$0.04 | Monthly |
| Memory pruning (if needed) | Sonnet | ~4000 | 2000 | ~$0.015 | Weekly |

### 12.3 Embedding Costs

| Operation | Model | Cost per 1K tokens | Frequency | Monthly Cost |
|-----------|-------|-------------------|-----------|-------------|
| File indexing (on write) | text-embedding-3-small | $0.00002/1K | ~50 files/day × 1K avg | ~$0.03 |
| Search queries | text-embedding-3-small | $0.00002/1K | ~100 queries/day × 0.1K | ~$0.006 |
| Full reindex | text-embedding-3-small | $0.00002/1K | ~5000 files × 1K, monthly | ~$0.10 |

### 12.4 Extraction Costs (Per Session)

| Extractor | Model | Tokens In | Tokens Out | Cost |
|-----------|-------|-----------|------------|------|
| Decision extractor | Haiku | ~3000 | 200 | ~$0.001 |
| Journal extractor | Haiku | ~3000 | 300 | ~$0.001 |
| Lesson extractor | Haiku | ~3000 | 200 | ~$0.001 |
| People extractor | Haiku | ~3000 | 200 | ~$0.001 |
| **Total per session** | | | | **~$0.004** |

### 12.5 Monthly Cost Estimates

| Usage Level | Sessions/Day | Monthly Extraction | Monthly Lifecycle | Monthly Embeddings | **Total Memory System Cost** |
|-------------|-------------|-------------------|------------------|--------------------|------------------------------|
| Light (5 sessions/day) | 5 | $0.60 | $0.50 | $0.15 | **~$1.25/month** |
| Medium (15 sessions/day) | 15 | $1.80 | $0.50 | $0.35 | **~$2.65/month** |
| Heavy (30 sessions/day) | 30 | $3.60 | $0.50 | $0.65 | **~$4.75/month** |

### 12.6 Reconstruction Cost

Full replay of all conversations (one-time, on algorithm change):

| Conversations | Extractor Cost Each | Total |
|--------------|-------------------|-------|
| 1,000 (6 months) | $0.004 | $4.00 |
| 5,000 (2+ years) | $0.004 | $20.00 |
| 10,000 (5+ years) | $0.004 | $40.00 |

Reconstruction is cheap enough to run experimentally on branches.

---

## Appendix: Key Design Decisions

| Decision | Chosen | Rejected | Why |
|----------|--------|----------|-----|
| Source of truth | Markdown files | SQLite, vector DB | Human-readable, git-trackable, agent uses same tools |
| Search index | SQLite FTS5 + sqlite-vec | Elasticsearch, Pinecone, pure ripgrep | Zero infrastructure, single file, hybrid BM25+vector |
| Conversation storage | One file per session, markdown | JSONL, SQLite, one file per day | Human-readable, natural boundaries, good git perf |
| Context assembly | Push-based compiler | Pull-based search (agent searches) | No tool call overhead, smaller models work, faster |
| Topic activation | Three-tier watcher pipeline | Single LLM call, user-only activation | Cheap (Tier 1+2 free), accurate (Tier 3 gate), autonomous |
| Memory lifecycle | Algorithmic extraction + scheduled condensation | Manual only, continuous extraction | Tuneable, replayable, A/B testable |
| Commit strategy | Conversations immediate, knowledge batched 30min | Per-message, per-hour, manual | Natural boundaries, low noise, low data loss risk |
| Embedding model | text-embedding-3-small | Local embeddings, larger models | Cheap enough ($0.00002/1K), good enough quality |
| Gate model | Haiku/Flash | Sonnet/Opus, no gate | $0.0002/call is negligible, prevents false positive topic activations |
| Branching model | main + explore/* + extract/* | GitFlow, trunk-based | Simple for single-agent, branches serve exploration and A/B testing |

---

*This is the blueprint. Build Phase 1 first, validate the conversation persistence and basic context compilation, then layer intelligence on top.*
