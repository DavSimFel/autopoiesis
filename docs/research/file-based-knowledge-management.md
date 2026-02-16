# File-Based Knowledge Management for an AI Agent

*Research & Opinionated Proposal for Autopoiesis*
*2026-02-16*

---

## TL;DR

**Copy OpenClaw's tiered injection pattern. Steal Claude Code's hierarchical CLAUDE.md and auto-memory. Add Cline's structured memory bank for project context. Use ripgrep as primary search, SQLite-FTS5 as index (not source of truth), skip embeddings initially. Files are the system of record. Git is your version history. The agent manages its own memory through explicit lifecycle rules.**

---

## 1. Survey of Existing Architectures

### What Production Systems Actually Do

| System | Memory Pattern | Files? | Search | Auto-loaded? |
|--------|---------------|--------|--------|-------------|
| **OpenClaw** | SOUL.md + USER.md + AGENTS.md + TOOLS.md (identity) + MEMORY.md (curated long-term) + memory/YYYY-MM-DD.md (daily) | ✅ Markdown | sqlite-vec hybrid (BM25 + vector) | Identity files every turn; daily notes on demand |
| **Claude Code** | Hierarchical CLAUDE.md (managed policy → project → user → local) + auto-memory in ~/.claude/projects/*/memory/ + .claude/rules/*.md | ✅ Markdown | None (all injected) | Yes, all loaded at session start; auto-memory capped at 200 lines |
| **Cline** | memory-bank/ with 6 structured files (projectbrief, productContext, activeContext, systemPatterns, techContext, progress) | ✅ Markdown | None (read on demand) | Via custom instructions trigger |
| **Cursor** | .cursorrules (single file, project root) + @-file references | ✅ Single file | Codebase indexing (embeddings) | .cursorrules auto-loaded |
| **Aider** | .aider.conf.yml + conventions file + repo map | ✅ Config + map | Tree-sitter repo map | Config auto-loaded |
| **Devin** | Knowledge base (user teaches patterns) + session plans | Opaque | Internal | Selective |
| **MemGPT/Letta** | Core memory (in-context, editable) + Recall (conversation DB) + Archival (vector DB) | ❌ Database | Vector + conversation search | Core memory always in context |
| **Khoj** | Markdown/org files + PDF/images indexed | ✅ User files | Embeddings + keyword | Indexed, retrieved on query |

### Key Insights

1. **Every successful system has a "always loaded" tier.** OpenClaw injects ~24KB of identity files. Claude Code loads all CLAUDE.md files in the hierarchy. MemGPT has "core memory" always in context. This is non-negotiable.

2. **Nobody relies on embeddings alone.** Claude Code uses zero search — just file injection. OpenClaw uses hybrid BM25+vector. Cursor uses embeddings for code but rules are injected. The trend is toward deterministic injection over probabilistic retrieval.

3. **Cline's memory bank is the best project-context pattern.** Six structured files that cover the full picture of a project. Better than "dump everything in MEMORY.md" because each file has a clear purpose and update frequency.

4. **Claude Code's hierarchy is the best scoping pattern.** Global → user → project → local. Each level overrides/extends the previous. This is how you scale from 1 project to 100.

5. **MemGPT's insight is correct but its implementation is wrong for us.** Tiered memory (hot/warm/cold) is the right mental model. But implementing it as a database defeats our goals of human-readability and git-trackability.

---

## 2. Knowledge Taxonomy for an Autonomous Agent

Not all knowledge is equal. Classification by **volatility** and **scope** determines where it lives:

| Category | Volatility | Scope | OpenClaw Equivalent | Auto-load? |
|----------|-----------|-------|-------------------|-----------|
| **Identity** (who am I) | Very low | Global | SOUL.md | ✅ Always |
| **User context** (who am I helping) | Low | Global | USER.md | ✅ Always |
| **Operational rules** (how I work) | Low | Global | AGENTS.md | ✅ Always |
| **Tool notes** (integration specifics) | Low-Medium | Global | TOOLS.md | ✅ Always |
| **Curated memory** (distilled lessons) | Medium | Global | MEMORY.md | ✅ Main session |
| **Active context** (what's happening now) | High | Session | (implicit in conversation) | ✅ Implicit |
| **Episodic memory** (what happened when) | Written once | Per-day | memory/YYYY-MM-DD.md | Recent 2 days |
| **Project context** (per-project state) | Medium | Per-project | (none) | On project activation |
| **Relationship memory** (people) | Low-Medium | Global | (in USER.md) | Via search |
| **Procedural memory** (how-to) | Low | Per-domain | (in AGENTS.md) | Via search |
| **Research/reference** | Written once | Per-topic | research/*.md | Via search |

---

## 3. The Proposed System

### Design Principles

1. **Files are the source of truth.** Always. No database is authoritative.
2. **Auto-loaded files must fit in ~25KB total.** This is the context budget. Exceed it and you're wasting tokens on low-value context.
3. **Everything else is searchable, not loaded.** The agent pulls what it needs.
4. **The agent maintains its own memory.** Capture, distill, prune — all agent responsibilities.
5. **Human can always read, edit, delete any file.** No opaque formats.
6. **Git tracks everything.** Free version history, free collaboration, free backup.

### Directory Structure

```
knowledge/
├── identity/                    # AUTO-LOADED (always in context)
│   ├── soul.md                  # Who I am, personality, values, communication style
│   ├── user.md                  # Who I'm helping, their world, preferences
│   ├── rules.md                 # How I operate, safety, workflows (AGENTS.md equivalent)
│   └── tools.md                 # Integration notes, API quirks, credentials refs
│
├── memory/                      # CURATED LONG-TERM (auto-loaded in main session)
│   └── core.md                  # Distilled lessons, key facts, relationship notes
│                                # Hard cap: 200 lines. Ruthlessly pruned.
│
├── journal/                     # EPISODIC (auto-load today + yesterday)
│   ├── 2026-02-16.md           # What happened today
│   ├── 2026-02-15.md           # What happened yesterday
│   └── ...                      # Older entries searchable, not loaded
│
├── projects/                    # PER-PROJECT (loaded when project is active)
│   ├── autopoiesis/
│   │   ├── context.md           # Current state, decisions, architecture
│   │   ├── progress.md          # What's done, what's next, blockers
│   │   └── notes.md             # Accumulated project knowledge
│   ├── excitingfit/
│   │   └── ...
│   └── _active.md               # List of currently active projects (auto-loaded)
│
├── people/                      # RELATIONSHIP MEMORY (searchable)
│   ├── _index.md                # Quick reference of all people
│   └── david.md                 # Deep context per person (when needed)
│
├── procedures/                  # HOW-TO (searchable)
│   ├── git-workflow.md
│   ├── notion-workflow.md
│   ├── email-workflow.md
│   └── ...
│
├── reference/                   # RESEARCH & REFERENCE (searchable)
│   ├── openclaw-agency-study.md
│   ├── file-based-knowledge-management.md
│   └── ...
│
└── archive/                     # COLD STORAGE (searchable, rarely accessed)
    ├── journal/                 # Old daily notes (>30 days)
    └── projects/                # Completed/abandoned projects
```

### What Gets Auto-Loaded (Context Budget: ~25KB)

| File | Budget | Load Condition |
|------|--------|---------------|
| `identity/soul.md` | ~3KB | Always |
| `identity/user.md` | ~4KB | Always |
| `identity/rules.md` | ~5KB | Always |
| `identity/tools.md` | ~5KB | Always |
| `memory/core.md` | ~3KB | Main session only |
| `journal/today.md` | ~2KB | Always (today + yesterday) |
| `journal/yesterday.md` | ~2KB | Always |
| `projects/_active.md` | ~1KB | Always |
| **Total** | **~25KB** | |

This matches OpenClaw's 24KB bootstrap budget. Everything else is retrieved on demand.

### File Naming Conventions

- **Journal entries**: `YYYY-MM-DD.md` (sorting for free)
- **Project dirs**: `kebab-case/` matching project name
- **Procedure files**: `verb-noun.md` or `domain-workflow.md`
- **Reference files**: descriptive `topic-subtopic.md`
- **Index files**: `_index.md` (underscore prefix = meta-file)
- **Active tracking**: `_active.md` (lists what's currently relevant)

---

## 4. Retrieval Strategy

### Primary: Deterministic Injection (No Search Needed)

The auto-loaded files handle 80% of what the agent needs to know. Identity, rules, recent context, active projects — all injected every session. This is what Claude Code gets right: **if it's important enough to need, it's important enough to always load.**

### Secondary: ripgrep (Fast, Simple, Sufficient)

```bash
# Find mentions of "Notion" across all knowledge
rg -l "Notion" knowledge/

# Find recent references to a person
rg -l "Christina" knowledge/journal/ knowledge/people/

# Full-text search with context
rg -C 2 "API rate limit" knowledge/
```

ripgrep is fast enough for 10,000+ files. It handles 90% of "find me information about X" queries. No index needed, no maintenance overhead, works on any file immediately after creation.

### Tertiary: SQLite FTS5 Index (Optional Acceleration)

For when ripgrep isn't enough (fuzzy matching, ranking, complex queries):

```python
# Build index from files (run periodically or on file change)
def rebuild_index():
    for path in knowledge_dir.rglob("*.md"):
        content = path.read_text()
        db.execute("""
            INSERT OR REPLACE INTO knowledge_fts(path, content, modified)
            VALUES (?, ?, ?)
        """, (str(path), content, path.stat().st_mtime))

# Search with ranking
def search(query: str, limit: int = 10):
    return db.execute("""
        SELECT path, snippet(knowledge_fts, 1, '**', '**', '...', 32)
        FROM knowledge_fts WHERE knowledge_fts MATCH ?
        ORDER BY rank LIMIT ?
    """, (query, limit)).fetchall()
```

**Key difference from current system**: SQLite is a *search index*, not the *source of truth*. Files can exist without being indexed. The index can be rebuilt from scratch at any time. If the DB is deleted, nothing is lost.

### Skip Embeddings (For Now)

Embeddings add:
- API cost per indexing operation
- Latency for embedding generation
- Complexity (embedding model choice, dimension, distance metric)
- A dependency on an external service

What they give you:
- Semantic similarity ("find things *related to* X even if they don't mention X")

For a personal agent with <10K files, this isn't worth it yet. ripgrep + FTS5 cover keyword and fuzzy matching. The agent can always rephrase queries. **Add embeddings later if search quality becomes a bottleneck.**

---

## 5. Memory Lifecycle

### Capture (During Interaction)

The agent writes to `journal/YYYY-MM-DD.md` during or after interactions:

```markdown
## 2026-02-16

### Project: autopoiesis
- Decided to replace SQLite memory with file-based system
- Key insight: files as source of truth, SQLite as optional index
- David wants human-readable, git-trackable knowledge

### People
- Christina mentioned gym scheduling issues — follow up tomorrow
```

**Rules:**
- Bullet points, not prose
- Group by topic, not time
- Only write what's worth remembering (not "checked email, nothing new")

### Distillation (Periodic — Every Few Days)

During maintenance cycles (heartbeats, scheduled tasks):

1. Read journal entries from the past week
2. Extract significant events, decisions, lessons
3. Update `memory/core.md` with distilled insights
4. Update `projects/*/context.md` with project-relevant info
5. Update `people/*.md` if relationship context changed
6. Move journal entries >30 days to `archive/journal/`

### Pruning (Continuous)

`memory/core.md` has a **hard cap of 200 lines**. When it grows beyond:
1. Remove entries that are now captured in more specific files (project notes, people files)
2. Merge redundant entries
3. Remove stale information (superseded decisions, resolved issues)
4. Archive to `archive/` if historically valuable but not operationally relevant

### Consolidation (Monthly)

1. Review all `projects/` dirs — archive completed projects
2. Review `people/` — merge or remove stale entries
3. Review `procedures/` — update outdated workflows
4. Check `memory/core.md` for staleness
5. Git commit with message `chore: monthly knowledge maintenance`

---

## 6. SQLite vs Files: Honest Comparison

| Dimension | SQLite | Files | Winner |
|-----------|--------|-------|--------|
| Human readability | ❌ Opaque binary | ✅ Open in any editor | Files |
| Git tracking | ❌ Binary diffs useless | ✅ Line-level diffs | Files |
| Human editability | ❌ Need SQL or tool | ✅ Any text editor | Files |
| Structured queries | ✅ Full SQL | ❌ grep only | SQLite |
| Concurrent access | ✅ WAL mode | ⚠️ File locking needed | SQLite |
| Full-text search | ✅ FTS5, fast, ranked | ⚠️ ripgrep (fast but unranked) | SQLite |
| Portability | ✅ Single file | ✅ Any filesystem | Tie |
| Composability | ❌ Agent needs SQL | ✅ Agent uses same read/write tools | Files |
| Backup/restore | ✅ Single file copy | ✅ Git push | Tie |
| Scale (>10K entries) | ✅ Handles millions | ⚠️ Directory listing slows | SQLite |
| Debuggability | ❌ Need sqlite3 CLI | ✅ cat/less/grep | Files |

### The Right Answer: Both

**Files as source of truth + SQLite as search accelerator.**

This is what OpenClaw already does. The key change for Autopoiesis:
- Drop SQLite as the *primary* memory store
- Make files the canonical representation
- Keep SQLite FTS5 as an optional index rebuilt from files
- If the index is stale or missing, fall back to ripgrep

### What Autopoiesis Loses by Dropping SQLite as Primary

1. **Atomic transactions** — mitigated by file-level writes (a single markdown file is effectively atomic)
2. **Structured metadata** — mitigated by frontmatter in markdown files
3. **Fast count/aggregate queries** — mitigated by index files (_active.md, _index.md)
4. **Concurrent write safety** — mitigated by single-agent writes (the agent is the only writer during a session)

### What Autopoiesis Gains

1. **David can open any file and see exactly what the agent knows**
2. **Git history shows how knowledge evolved**
3. **Agent uses the same tools for memory as for everything else** (no special memory API)
4. **No migration needed when changing search backends**
5. **Files survive any code change** — they're just markdown

---

## 7. What's Better Than OpenClaw's Pattern

### Improvements to Copy/Adapt

| Feature | OpenClaw | Proposed | Why Better |
|---------|---------|----------|-----------|
| Project memory | None (all in MEMORY.md) | `projects/*/` with structured files | Per-project isolation, doesn't bloat global memory |
| People memory | Mixed into USER.md/MEMORY.md | `people/` directory | Searchable, scalable, doesn't bloat auto-loaded files |
| Procedures | Mixed into AGENTS.md | `procedures/` directory | AGENTS.md stays focused on rules; procedures are reference material |
| Active project tracking | None | `projects/_active.md` | Agent knows what's current without loading all project dirs |
| Memory cap | "Keep under 200 lines" (advisory) | Hard 200-line cap with automated pruning | Actually enforced |
| Archive | None | `archive/` for old journal + completed projects | Keeps working dirs clean |
| Hierarchical rules | Single AGENTS.md | Could add per-project rules (like Claude Code's .claude/rules/) | Project-specific conventions without global bloat |

### What to Copy Directly from OpenClaw

1. **Identity files injected every turn** — SOUL.md, USER.md, AGENTS.md, TOOLS.md pattern is excellent
2. **Daily journal pattern** — YYYY-MM-DD.md works perfectly
3. **Curated long-term memory** — MEMORY.md (→ memory/core.md) with size cap
4. **Memory maintenance in heartbeats** — periodic distillation is the right cadence
5. **Pre-compaction memory flush** — save important context before context window resets
6. **Files as source of truth, index as accelerator** — the hybrid approach

### What to Copy from Claude Code

1. **Hierarchical scope** — global user preferences → project rules → local overrides
2. **Auto-memory** — agent writes its own notes that persist across sessions
3. **200-line cap on auto-memory** — prevents context bloat
4. **Rules directory** — modular `.claude/rules/*.md` for topic-specific conventions

### What to Copy from Cline Memory Bank

1. **Structured project files** — context.md, progress.md, notes.md (adapted from their 6-file pattern)
2. **Explicit "initialize" and "update" commands** — clear triggers for memory maintenance

---

## 8. Implementation Plan

### Migration from SQLite memory_store

1. **Export**: Dump all SQLite entries to markdown files organized by date/topic
2. **Restructure**: Sort exported entries into the new directory structure
3. **Build tools**: Replace `memory_store.py` with file-based equivalents:
   - `memory_write(category, content)` → appends to appropriate file
   - `memory_search(query)` → ripgrep wrapper, falls back to FTS5
   - `memory_read(path)` → direct file read
4. **Build index**: FTS5 index builder that watches/scans the knowledge directory
5. **Test**: Verify search quality against the old system

### Tool Interface (Replacing memory_tools.py)

```python
# Simple, composable tools — the agent already has read/write/exec

def memory_save(category: str, content: str):
    """Save to today's journal or a specific category file."""
    if category == "journal":
        path = f"knowledge/journal/{today()}.md"
        append(path, content)
    elif category == "project":
        path = f"knowledge/projects/{project}/notes.md"
        append(path, content)
    # etc.

def memory_search(query: str, scope: str = "all") -> list[SearchResult]:
    """Search knowledge files. Scope: all, journal, projects, people, etc."""
    # Try ripgrep first (fast, no index needed)
    results = ripgrep(query, f"knowledge/{scope}/")
    if not results:
        # Fall back to FTS5 for fuzzy matching
        results = fts5_search(query, scope)
    return results
```

**Or even simpler**: Don't build special memory tools at all. The agent already has `read`, `write`, `edit`, and `exec` (for ripgrep). Memory management is just file management with conventions. The "tools" are the conventions documented in `identity/rules.md`.

### Concurrent Write Handling

- **Single writer principle**: The agent is the primary writer. Human edits happen between sessions.
- **Git as conflict resolver**: If both edit the same file, git merge handles it.
- **Atomic file writes**: Write to temp file, then rename. Prevents partial writes.
- **Last-write-wins for journal**: Journal entries are append-only, so conflicts are rare.

### Scaling Considerations

| Scale | Files | Strategy |
|-------|-------|----------|
| <100 | All searchable via ripgrep | No index needed |
| 100-1000 | ripgrep still fast (<100ms) | FTS5 index optional |
| 1000-10000 | ripgrep ~200ms | FTS5 recommended, archive aggressively |
| >10000 | ripgrep slows | FTS5 required, embeddings worth considering |

For a personal agent, you'll hit 1000 files after ~3 years of daily use. This is not a scaling problem for the foreseeable future.

---

## 9. The Recommendation

**Build the directory structure above. Use OpenClaw's injection pattern for identity files. Use ripgrep as primary search. Keep SQLite FTS5 as an optional accelerator, not the source of truth. Skip embeddings. Let the agent manage its own memory through file operations with clear lifecycle rules documented in `identity/rules.md`.**

The system is:
- **Human-readable**: Every piece of knowledge is a markdown file
- **Git-trackable**: Full version history, diffable, mergeable
- **Inspectable**: `cat knowledge/memory/core.md` shows exactly what the agent "knows"
- **Composable**: The agent uses standard file tools, no special memory API needed
- **Searchable**: ripgrep for 90% of queries, FTS5 for the rest
- **Scalable**: Proven patterns, clear archival strategy, hard caps on auto-loaded content

The most important insight: **memory management is just file management with good conventions.** The simpler the system, the more likely the agent (and the human) will actually use it correctly.
