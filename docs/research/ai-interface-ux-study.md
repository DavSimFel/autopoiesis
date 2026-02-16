# Human-AI Interaction Interface: UX/UI Deep Research Study

**Date:** 2026-02-16  
**Context:** UI for a fully capable, multimodal AI agent system (Silas) with tool execution, approval workflows, memory, sub-agents, and persistent context.

---

## Table of Contents

1. [Human-AI Interaction Patterns](#1-human-ai-interaction-patterns)
2. [Interface Functionality](#2-interface-functionality)
3. [Visual Design Language](#3-visual-design-language)
4. [Technical Architecture](#4-technical-architecture)
5. [Recommended Stack](#5-recommended-stack)
6. [Build Order (MVP → Full)](#6-build-order)

---

## 1. Human-AI Interaction Patterns

### 1.1 Workflow Patterns

Users interact with a capable AI in four distinct modes. The interface must support seamless transitions between all four:

| Mode | Description | When Used | UI Pattern |
|------|-------------|-----------|------------|
| **Command** | Quick, imperative requests | "Send this email", "Create a task" | Input bar with slash commands, keyboard shortcuts |
| **Conversation** | Exploratory dialogue | Brainstorming, Q&A, analysis | Chat thread with branching |
| **Delegation** | Hand off complex work | "Research X and write a report" | Task card with progress tracking, approval gates |
| **Monitoring** | Passive oversight of autonomous work | Long-running tasks, background agents | Dashboard with status feeds, notification badges |

**Key insight (Linear's "Design for the AI Age"):** Chat is a "weak and generic form." The interface should be a **workbench** — a structured environment where AI operates within visible, purpose-built UI, not just a conversation window. Chat is one tool on the workbench, not the workbench itself.

**Recommendation:** Default to a **workbench layout** with chat as a panel (not the whole screen). The workbench includes: active task cards, canvas/workspace, and a persistent sidebar for navigation. Chat can be expanded to full-screen when the interaction is purely conversational.

### 1.2 Trust & Control

This is the most critical design challenge. Research from Google's PAIR Guidebook, Microsoft's HAX Toolkit, and Anthropic's usage patterns converges on these principles:

#### Approval Flows

| Risk Level | Pattern | Example |
|-----------|---------|---------|
| **No risk** | Auto-execute, log only | Read files, search web, answer questions |
| **Low risk** | Execute + notify (undo window) | Create/edit documents, schedule events |
| **Medium risk** | Preview + one-click approve | Send emails, modify data, install packages |
| **High risk** | Full review + explicit approve | Delete data, financial transactions, external API calls |

**UI implementation:**
- **Inline approval cards** in the chat stream — not modal dialogs. Show what the AI wants to do, why, and let the user approve/deny/edit inline.
- **Standing approvals** as a settings panel: "Always allow web searches", "Always ask before sending emails"
- **Undo timeline**: A global undo rail (like Figma's version history) showing all actions taken, with point-in-time rollback
- **Audit trail**: Collapsible "activity log" showing every tool call, gate evaluation, and approval decision

#### Constraint Setting

Users should set constraints **proactively** (before delegation), not just reactively:
- **Budget limits**: Token/cost caps per task, visible as a progress bar
- **Tool permissions**: Toggle which tools the AI can use (per task or globally)
- **Scope boundaries**: "Only modify files in /src", "Don't contact anyone external"
- **Time limits**: Auto-escalate if task takes > N minutes

**Reference:** Microsoft Copilot's principle: "The human is the pilot." Position every action verb as user-initiated: "Summarize with AI" not "AI summarizes."

### 1.3 Attention Management

When should the AI interrupt vs. queue vs. stay silent?

| Urgency | Behavior | Notification |
|---------|----------|-------------|
| **Blocking** (needs approval to continue) | Interrupt immediately | Push notification + sound + badge |
| **Complete** (task finished) | Notify, don't interrupt | Badge + toast, no sound |
| **Informational** (progress update) | Queue silently | In-app badge only |
| **Ambient** (background learning) | Don't notify | Visible only in dashboard |

**Design rules:**
1. **Never interrupt for information the user didn't ask for** — this erodes trust faster than any other pattern
2. **Batch notifications** — if 3 sub-tasks complete in 10 seconds, send one notification, not three
3. **Respect focus mode** — when user is typing/working, queue everything except blocking approvals
4. **Notification center** — a dedicated panel (like macOS Notification Center) for all AI activity, searchable and filterable
5. **Smart urgency detection** — deadline-approaching items escalate automatically

### 1.4 Multimodal Switching

Research on modality preferences (Apple HIG, Google PAIR):

| Modality | Best For | Context |
|----------|----------|---------|
| **Text** | Precise instructions, code, data, async work | Desktop, focused work, public spaces |
| **Voice** | Quick commands, hands-busy, mobile | Driving, cooking, walking, eyes-occupied |
| **Screen share** | Debugging, design review, "show me" | Complex visual context |
| **Live video** | Physical world tasks ("what is this?") | Camera-based identification, spatial tasks |

**Transition design:**
- **Voice → Text**: Auto-transcription always visible; user can edit transcript before sending
- **Text → Voice**: Mic button in input bar; long-press for push-to-talk, tap for toggle
- **Any → Screen share**: Quick-share button that captures current screen/window/selection
- **Seamless context**: Switching modality shouldn't lose conversation context

**Voice-specific UX:**
- Push-to-talk as default (always-listening is privacy-hostile for a personal assistant)
- Voice activity indicator: Subtle waveform animation when AI is "listening"
- Interruption: User speaking should cancel AI's current audio output immediately
- Transcription: Show real-time transcript with confidence highlighting (dim uncertain words)

### 1.5 Delegation Depth

| Depth | Duration | Reporting | User Involvement |
|-------|----------|-----------|-----------------|
| **Instant** | < 5 sec | Inline result | None — just shows answer |
| **Quick task** | 5 sec – 2 min | Progress indicator + result | Minimal — approval if needed |
| **Work item** | 2 min – 1 hr | Task card with live updates | Periodic check-ins, approval gates |
| **Project** | Hours – days | Dashboard with milestones | Goal-setting, reviews, steering |

**Handoff UX for work items:**
1. AI presents a **plan preview** before executing (expandable to see sub-steps)
2. User approves, edits, or rejects the plan
3. During execution: **live activity feed** in a collapsible panel (not blocking the chat)
4. On completion: **summary card** with results, artifacts, and verification status
5. On failure: **error card** with what went wrong, what was tried, and options (retry, modify, escalate)

### 1.6 Context Sharing

Efficient context sharing is about reducing the gap between "what the user sees" and "what the AI knows":

| Method | Use Case | Implementation |
|--------|----------|---------------|
| **Drag & drop** | Files, images, screenshots | Drop zone in chat input area |
| **Clipboard paste** | Images, text, URLs | Auto-detect content type on paste |
| **Screen capture** | Current visual context | Keyboard shortcut (⌘+Shift+S) or toolbar button |
| **File picker** | Workspace files | Tree view of accessible files |
| **URL reference** | Web content | Paste URL → AI fetches and summarizes |
| **@mention** | Reference previous messages/artifacts | Searchable mention picker |

**Key principle:** The AI should never ask "can you share your screen?" — the UI should make sharing so easy that context flows naturally.

### 1.7 Multi-Agent Visibility

When the AI spawns sub-agents (as Silas does with Proxy → Planner → Executor):

**User-facing model:** Don't expose the multi-agent architecture directly. Instead, show **task decomposition**:

```
📋 "Research competitors and write report"
├── 🔍 Searching web for competitors... ✅
├── 📄 Reading 12 sources... ✅  
├── ✍️ Writing report draft... ⏳ (73%)
└── ✅ Verification pending
```

**Design rules:**
1. **One AI identity** — users interact with "the AI," not individual agents. The routing is an implementation detail.
2. **Expand on demand** — collapsed by default, expandable to see sub-tasks, tool calls, and intermediate results
3. **Cancel at any level** — user can cancel the whole task or individual sub-tasks
4. **Resource visibility** — show token/cost usage per sub-task (for power users, in a collapsible section)

### 1.8 Group Dynamics

When AI participates in group conversations (Discord, Slack, team chat):

| Principle | Implementation |
|-----------|---------------|
| **Speak when spoken to** | Respond to @mentions and direct questions |
| **Don't dominate** | Never send more than 2 consecutive messages |
| **Match tone** | Formal in work channels, casual in social |
| **Defer to humans** | If a human already answered, don't pile on |
| **Use reactions** | 👍 to acknowledge without adding noise |
| **Thread replies** | Long responses go in threads, not main channel |

### 1.9 Error Recovery

Errors fall into three categories, each with distinct UX:

| Error Type | Example | UX Pattern |
|-----------|---------|------------|
| **Misunderstanding** | AI did the wrong thing | "Not what I meant" button → clarification dialog with original intent |
| **Failure** | Tool execution failed | Error card with: what failed, why, retry/modify/skip options |
| **Hallucination** | AI stated something incorrect | Inline correction (user edits AI message) → AI acknowledges and adjusts |

**Key patterns:**
- **Edit sent messages** — user can edit their own messages to refine instructions, AI re-processes from the edit point
- **Branch conversations** — "Try again differently" creates a fork, preserving the original path
- **Correction memory** — corrections are stored so the same mistake isn't repeated
- **Graceful degradation** — if a tool is unavailable, AI explains what it can't do and suggests alternatives

### 1.10 Progressive Disclosure

| Layer | Audience | What's Visible |
|-------|----------|---------------|
| **Simple** | New users | Chat input, AI responses, basic approve/deny |
| **Standard** | Regular users | + Task cards, file browser, notification center, settings |
| **Power** | Advanced users | + Audit log, token usage, raw tool calls, plan YAML, custom constraints |
| **Developer** | System admins | + Gate configuration, model selection, system prompts, API access |

**Implementation:** Not separate modes — progressive disclosure through:
- Collapsible sections (default collapsed for simple, expanded for power)
- Settings toggle: "Show detailed activity" 
- Keyboard shortcuts for power features
- Right-click context menus with advanced options

---

## 2. Interface Functionality

### 2.1 Text Chat

| Feature | Priority | Implementation Notes |
|---------|----------|---------------------|
| Streaming text | P0 | Token-by-token rendering with cursor animation |
| Rich content | P0 | Markdown with tables, code blocks (syntax highlighted), LaTeX, images |
| Message editing | P0 | Edit sent messages → AI reprocesses from that point |
| Branching | P1 | Fork conversation at any message; tree view in sidebar |
| Threading | P1 | Reply to specific messages; collapsible thread view |
| Search | P1 | Full-text search across all conversations with filters |
| Bookmarks/pins | P2 | Pin important messages or AI outputs |
| Message reactions | P2 | Quick feedback (👍/👎) that feeds into AI memory |
| File attachments | P0 | Drag-drop, paste, file picker — images, docs, code files |
| Code execution | P1 | Inline "Run" button on code blocks (sandboxed) |
| Copy controls | P0 | One-click copy for code blocks, tables, entire responses |

**Streaming UX specifics:**
- Show a subtle pulsing cursor during generation
- Allow user to **stop generation** at any point
- Progressive rendering: headings and structure appear first, then fill in
- Don't scroll-jack: if user has scrolled up, don't auto-scroll. Show a "↓ New content" badge instead

### 2.2 Voice

| Feature | Priority | Notes |
|---------|----------|-------|
| Push-to-talk | P0 | Hold spacebar or dedicated button; default mode |
| Voice toggle | P1 | Tap to start/stop continuous listening |
| Real-time transcription | P0 | Show transcription as user speaks |
| AI voice output | P1 | Natural TTS with interruption support |
| Voice activity indicator | P0 | Visual feedback when mic is active |
| Wake word (optional) | P3 | "Hey Silas" — only for hands-free scenarios |
| Language detection | P2 | Auto-detect and transcribe multiple languages |

### 2.3 Video/Screen

| Feature | Priority | Notes |
|---------|----------|-------|
| Screen sharing for context | P1 | Share screen/window/region so AI can see what you see |
| Camera input | P2 | "What is this?" — point camera at something |
| AI-generated visuals | P1 | Charts, diagrams, code previews rendered inline |
| Live annotation | P2 | AI can highlight/annotate on shared screen |

### 2.4 Canvas/Workspace

The **canvas** is a persistent, shared workspace that lives alongside (or replaces) chat for certain tasks. Inspired by: Claude's Artifacts, Cursor's editor, Notion's blocks.

| Feature | Priority | Notes |
|---------|----------|-------|
| Document editor | P1 | Rich text editing with AI collaboration (suggest/edit modes) |
| Code editor | P1 | Monaco-based with AI inline completions |
| Diagram viewer | P2 | Mermaid/D2 diagram rendering |
| Split view | P1 | Chat on left, canvas on right |
| Version history | P1 | Every AI edit tracked, diffable, revertable |
| Multiple canvases | P2 | Tabs/panels for different artifacts |

### 2.5 Notifications

| Platform | Behavior |
|----------|----------|
| **Desktop** | Native OS notifications for blocking/complete; toast for informational |
| **Mobile** | Push notifications with rich previews; grouped by task |
| **Watch** | Haptic for blocking approvals only |
| **Email** | Daily digest of completed tasks (optional) |

**Cross-platform sync:** Read state syncs instantly. Dismissing on one device dismisses everywhere.

### 2.6 Settings & Constraints

Organized in three tiers:

**Quick Settings (always accessible):**
- Current model/mode toggle
- Voice on/off
- Notification level (all / important / blocking only)

**AI Behavior (settings panel):**
- Tool permissions (toggles per tool)
- Standing approvals manager
- Budget limits (tokens, cost, time)
- Response style (concise ↔ detailed slider)
- Memory management (view, edit, delete memories)

**Advanced (developer panel):**
- System prompt editor
- Gate configuration
- Model selection per agent role
- API key management
- Export/import configuration

### 2.7 History & Memory

| Feature | Description |
|---------|-------------|
| **Conversation list** | Sidebar with all conversations, searchable, sortable by date/topic |
| **Memory browser** | Searchable list of stored memories with categories, importance, taint level |
| **Memory editor** | Edit/delete individual memories; bulk operations |
| **"What do you know about X?"** | Natural language memory query |
| **Context inspector** | What the AI currently "sees" — system prompt, active memories, context budget usage |

### 2.8 Dashboard

| Widget | Content |
|--------|---------|
| **Active tasks** | Currently running work items with progress bars |
| **Recent activity** | Timeline of recent actions, approvals, completions |
| **Cost tracker** | Token usage, API costs, budget remaining (daily/monthly) |
| **System health** | Connection status, model availability, queue depth |
| **Quick actions** | Frequently used commands, pinned workflows |

---

## 3. Visual Design Language

### 3.1 Design Philosophy

**Recommendation: "Warm Minimal"** — the intersection of Linear's precision and Apple's warmth.

Principles:
1. **Content-first density** — No decorative chrome. Every pixel serves communication.
2. **Quiet confidence** — The AI is capable; the UI doesn't need to prove it with flashy effects.
3. **Readable at scale** — Long AI outputs must be scannable. Use clear hierarchy, generous whitespace, and visible structure.
4. **Dark mode primary** — AI/developer tools are used in extended sessions. Dark mode reduces eye strain. Light mode as a supported alternative.
5. **Subtle life** — Micro-animations that suggest intelligence without demanding attention.

**Anti-patterns to avoid:**
- Glassmorphism (trendy but reduces readability)
- Excessive gradients (distracting for text-heavy content)
- Chat bubbles with tails (waste space; use alignment + subtle background differentiation)
- Anthropomorphic avatars (per Microsoft's guidance: avoid humanizing the AI)

**Reference apps and what to steal:**

| App | Steal This |
|-----|-----------|
| **Linear** | Information density, keyboard-first navigation, dark mode palette |
| **Raycast** | Command palette UX, speed, progressive disclosure |
| **Arc Browser** | Sidebar organization, spatial layout, playful-but-professional tone |
| **Vercel Dashboard** | Clean data presentation, deployment status patterns |
| **Stripe Docs** | Typography hierarchy, code block styling |
| **Apple Intelligence** | Subtle glow effects for AI activity, system integration feel |
| **Nothing OS** | Dot-matrix thinking indicators, monospace accents |
| **Teenage Engineering** | Intentional constraints, personality through typography |

### 3.2 Color System

#### Primary Palette (Dark Mode)

| Role | Color | Hex | Usage |
|------|-------|-----|-------|
| **Background** | Near-black | `#0A0A0B` | Main canvas |
| **Surface** | Dark gray | `#141416` | Cards, panels, elevated surfaces |
| **Surface elevated** | Medium-dark | `#1C1C1F` | Hover states, active items |
| **Border** | Subtle gray | `#2A2A2E` | Dividers, card borders |
| **Text primary** | Off-white | `#EDEDEF` | Main text, headings |
| **Text secondary** | Medium gray | `#8B8B8F` | Labels, metadata, timestamps |
| **Text tertiary** | Dark gray | `#5A5A5E` | Disabled text, placeholders |

#### Accent & Semantic

| Role | Color | Hex | Usage |
|------|-------|-----|-------|
| **Accent** | Soft blue | `#6E8AFA` | Links, active states, AI activity indicator |
| **Success** | Muted green | `#4ADE80` | Completed tasks, approvals |
| **Warning** | Warm amber | `#FBBF24` | Pending approvals, budget warnings |
| **Error** | Soft red | `#F87171` | Failures, blocked actions |
| **AI thinking** | Subtle violet glow | `#8B5CF6` | Thinking indicator, processing states |

#### Light Mode

Invert the gray scale. Background: `#FAFAFA`, Surface: `#FFFFFF`, Text: `#111113`. Keep accents the same but increase saturation by ~10%.

#### Accessibility

- All text meets WCAG 2.1 AA (4.5:1 contrast ratio minimum)
- Interactive elements meet 3:1 contrast against background
- Never rely on color alone — always pair with icons or text labels

### 3.3 Typography

**Recommended font stack:**

| Role | Font | Fallback | Why |
|------|------|----------|-----|
| **UI (sans-serif)** | **Inter** | system-ui, -apple-system | Industry standard for UI. Excellent legibility at small sizes, variable font with optical sizing. Used by Linear, Vercel, Raycast. |
| **Monospace** | **JetBrains Mono** | ui-monospace, Menlo | Superior code readability, ligatures for operators, designed for extended reading. |
| **Display (optional)** | **Space Grotesk** | Inter | For hero text, onboarding, marketing. Geometric with character. Pairs well with both Inter and JetBrains Mono. |

**Type scale (base: 14px):**

| Level | Size | Weight | Line Height | Usage |
|-------|------|--------|-------------|-------|
| **Display** | 32px | 700 | 1.2 | Page titles, onboarding |
| **H1** | 24px | 600 | 1.3 | Section headers |
| **H2** | 18px | 600 | 1.4 | Sub-section headers |
| **H3** | 16px | 600 | 1.4 | Card titles |
| **Body** | 14px | 400 | 1.6 | Main text, AI responses |
| **Body small** | 13px | 400 | 1.5 | Secondary text, metadata |
| **Caption** | 12px | 400 | 1.4 | Timestamps, labels |
| **Code** | 13px | 400 | 1.5 | Code blocks, inline code |

**AI response typography:** Use 14px body with 1.6 line height. For long outputs, add subtle left-border accent (2px, accent color at 20% opacity) to distinguish AI content from user content.

### 3.4 Animation & Motion

| Element | Animation | Duration | Easing |
|---------|-----------|----------|--------|
| **Thinking indicator** | Three dots with staggered opacity pulse | 1.5s loop | ease-in-out |
| **Streaming text** | Characters appear with subtle fade-in | 20ms/char | ease-out |
| **Task progress** | Progress bar with smooth fill | 300ms | ease-out |
| **Panel transitions** | Slide + fade | 200ms | cubic-bezier(0.4, 0, 0.2, 1) |
| **Toast notifications** | Slide in from top-right, fade out | 200ms in, 150ms out | ease-out |
| **Approval card appear** | Scale from 0.95 + fade | 150ms | spring(1, 80, 10) |
| **Success confirmation** | Subtle green pulse on card | 400ms | ease-out |

**Motion principles:**
- **Fast** — No animation > 300ms for UI transitions. Users shouldn't wait for animations.
- **Purposeful** — Animation communicates state change, not decoration
- **Interruptible** — Any animation can be interrupted by user action
- **Reduced motion** — Respect `prefers-reduced-motion`: replace animations with instant state changes

### 3.5 Density & Spacing

**Base unit:** 4px grid

| Element | Spacing |
|---------|---------|
| **Message gap** | 8px (same sender), 16px (different sender) |
| **Section padding** | 16px |
| **Card padding** | 12px |
| **Input area height** | 48px minimum, grows to 200px max |
| **Sidebar width** | 260px (collapsible to 48px icon-only) |
| **Panel width** | 400px min, resizable |

**Message rendering:** Don't use chat bubbles. Use **alignment differentiation**:
- User messages: Right-aligned, subtle background (`Surface` color), full width available
- AI messages: Left-aligned, no background (or very subtle), full width
- System messages: Centered, muted text, small font

This saves ~30% horizontal space vs. traditional bubbles and scales better for long content.

### 3.6 Iconography

**Recommendation: Lucide Icons** (open source, consistent, 24px grid)
- Style: 1.5px stroke, rounded caps and joins
- Size: 16px for inline, 20px for buttons, 24px for navigation
- Color: Inherit from text color (secondary for decorative, primary for interactive)
- Animated icons for: loading (spinner), AI thinking (subtle pulse), voice (waveform)

### 3.7 Sound Design

| Event | Sound | Character |
|-------|-------|-----------|
| **Message sent** | Soft "pop" | Short, satisfying, non-intrusive |
| **Message received** | Gentle chime | Warm, 2-note ascending |
| **Approval needed** | Attention tone | Slightly urgent, distinct from received |
| **Task complete** | Completion chime | Resolved, 3-note ascending |
| **Error** | Soft discord | Low, brief, not alarming |
| **Voice mode start** | Subtle activation tone | Clean, indicates listening |
| **Voice mode end** | Deactivation tone | Complementary to start |

**All sounds optional, off by default for text-only interactions. On by default for voice mode.**

### 3.8 Responsive Design

**Desktop-first, responsive down.**

This is a productivity tool. Desktop is the primary use case. Mobile is for monitoring, quick approvals, and voice interaction — not for heavy work.

| Breakpoint | Layout | Primary Use |
|-----------|--------|-------------|
| **≥1280px** | Three-column: sidebar + chat + canvas | Full workbench |
| **≥768px** | Two-column: sidebar + main (chat or canvas) | Focused work |
| **<768px** | Single column with tab navigation | Mobile: monitoring, quick interactions |

**Mobile-specific adaptations:**
- Bottom navigation bar (chat, tasks, notifications, settings)
- Swipe gestures for navigation between sections
- Simplified approval cards (big approve/deny buttons)
- Voice as primary input mode

---

## 4. Technical Architecture

### 4.1 Database: PostgreSQL + JSONB (Not Dgraph)

**Verdict: Skip the graph DB. Use PostgreSQL.**

| Criterion | Dgraph | PostgreSQL + JSONB | Verdict |
|-----------|--------|-------------------|---------|
| **Data model fit** | Graph relationships natural for conversation threads, memory links | JSONB handles semi-structured data; recursive CTEs handle tree queries | Conversations are trees, not arbitrary graphs. PostgreSQL handles this well. |
| **Operational complexity** | Separate service, Raft consensus, custom query language (DQL/GraphQL) | Single service, mature tooling, SQL (universal knowledge) | PostgreSQL wins massively for a single-user self-hosted system |
| **Ecosystem** | Niche community, uncertain corporate future | Largest RDBMS ecosystem, extensions for everything | PostgreSQL |
| **Vector search** | Not built-in | pgvector extension — production-grade | PostgreSQL |
| **Full-text search** | Basic | Built-in tsvector or pg_trgm | PostgreSQL |
| **Performance** | Overkill for single-user | More than sufficient | PostgreSQL |

**Recommendation:** PostgreSQL 16+ with:
- `pgvector` for memory embeddings/semantic search
- JSONB columns for flexible metadata (tool call results, plan YAML, etc.)
- Standard relational tables for conversations, messages, tasks, audit log
- Recursive CTEs for conversation tree queries

**Why not SurrealDB?** Interesting multi-model DB but immature (pre-1.0 stability), small community, risky for production. PostgreSQL is boring and correct.

**Note:** Silas v0.1.0 uses SQLite, which is fine for the agent runtime. The web UI can use PostgreSQL for its own data layer (user sessions, UI state, cached data) while Silas continues with SQLite internally. Or: start with SQLite for everything and migrate to PostgreSQL when multi-device/multi-user matters.

### 4.2 Backend: FastAPI (Confirmed)

**Verdict: FastAPI is the right choice.**

| Framework | Pros | Cons | Fit |
|-----------|------|------|-----|
| **FastAPI** | Async-native, WebSocket support, Pydantic integration, huge ecosystem, already used in Silas | Not the absolute fastest | ✅ Best fit — matches existing codebase |
| **Litestar** | Slightly faster, more opinionated | Smaller community, less ecosystem | Marginal gains, not worth switching |
| **Go (Fiber/Echo)** | Raw performance, goroutines | Different language from Silas, no Pydantic | Only if Python becomes a bottleneck (unlikely for single-user) |
| **Elixir (Phoenix)** | Best real-time story (channels, presence) | Different language/ecosystem, steep learning curve | Overkill for this use case |

**Key point:** Silas is already Python/FastAPI. The UI backend should be the same service (or a thin extension). Adding a Go or Elixir layer creates unnecessary complexity.

**Streaming pattern:** FastAPI + WebSocket for bidirectional streaming. SSE as a fallback for simpler clients.

### 4.3 Frontend Framework: Svelte 5 (Confirmed, with caveats)

**Verdict: Svelte 5 is a strong choice. React would also work. Svelte wins on DX and performance for a small team.**

| Framework | Pros | Cons | Fit |
|-----------|------|------|-----|
| **Svelte 5** | Excellent performance, small bundles, runes reactivity is elegant, less boilerplate, great DX | Smaller ecosystem than React, fewer AI-specific component libraries | ✅ Great for a small team building a custom UI |
| **React 19** | Largest ecosystem, most AI UI libraries (assistant-ui, Vercel AI SDK), easier hiring | More boilerplate, larger bundles, virtual DOM overhead | Good fallback if ecosystem matters more |
| **Solid** | Best performance, fine-grained reactivity | Tiny ecosystem, fewer components | Too niche |
| **Vue 3** | Good middle ground | Smaller AI ecosystem than React | No compelling advantage |

**Risk with Svelte:** The `assistant-ui` library (React) provides excellent AI chat primitives (streaming, tool call rendering, inline approvals). No equivalent exists for Svelte. You'll build more from scratch.

**Mitigation:** Use SvelteKit for routing/SSR + build custom chat components. The streaming/WebSocket layer is framework-agnostic anyway.

### 4.4 UI Library: shadcn-svelte (Not DaisyUI)

**Verdict: shadcn-svelte over DaisyUI.**

| Library | Pros | Cons | Fit |
|---------|------|------|-----|
| **shadcn-svelte** | Full source ownership, highly customizable, accessible (built on Bits UI/Melt UI), Tailwind-based, actively maintained for Svelte 5 | Not a traditional library (copies code into project) | ✅ Best for a custom design system |
| **DaisyUI** | Quick to prototype, many themes, easy to use | Framework-agnostic (no Svelte components), limited customization depth, "themed Bootstrap" feel | ❌ Too opinionated, doesn't match the "warm minimal" vision |
| **Skeleton UI** | Svelte-native, good out-of-box | Stalled development, migration issues with Svelte 5 | ❌ Risk of abandonment |
| **Melt UI** | Headless, accessible primitives | Low-level, need to build everything on top | Use as foundation (shadcn-svelte already uses it) |

**shadcn-svelte approach:** Copy component source into your project → full control over every detail → build your design system on top of accessible primitives.

### 4.5 Bundler: Vite (Confirmed)

**Vite is the correct choice.** No alternative is worth considering for a Svelte project. Fast HMR, excellent plugin ecosystem, SvelteKit uses it natively.

### 4.6 Real-Time Communication

| Protocol | Use Case | Why |
|----------|----------|-----|
| **WebSocket** | Primary: chat messages, streaming AI responses, task updates, approvals | Bidirectional, persistent connection, low latency (10-50ms). Already in Silas. |
| **SSE** | Fallback: read-only update streams when WebSocket isn't available | Simpler, works through proxies/CDNs, auto-reconnect built in |
| **WebRTC** | Voice/video only: real-time audio/video with AI | Required for low-latency audio (<20ms P2P). Use for voice mode and screen sharing. |

**Architecture:**
- WebSocket for all text/data communication
- WebRTC for voice and video channels (can use a media server like LiveKit for server-side processing)
- Fallback: SSE for environments that block WebSocket

### 4.7 State Management

**Svelte 5 runes + server state pattern:**

| Layer | Tool | Responsibility |
|-------|------|---------------|
| **Server state** | Custom WebSocket store | Messages, tasks, approvals — source of truth is server |
| **UI state** | Svelte 5 `$state` runes | Panel visibility, scroll position, input drafts, local preferences |
| **Derived state** | Svelte 5 `$derived` | Filtered messages, unread counts, task groupings |
| **Persistent local** | `localStorage` wrapper | Theme preference, sidebar width, collapsed sections |

**Key pattern:** Optimistic UI for user messages (show immediately, confirm via WebSocket ACK). Pessimistic UI for AI actions (show only after server confirms).

### 4.8 Mobile Strategy

**Verdict: PWA first, Tauri later if needed.**

| Approach | Pros | Cons | Recommendation |
|----------|------|------|---------------|
| **PWA** | Single codebase, instant deployment, no app store | Limited iOS push notifications (improving), no system-level integration | ✅ MVP and primary strategy |
| **Tauri v2** | Native wrapping, system tray, smaller than Electron, mobile support | Adds build complexity, Rust dependency | ✅ Phase 2: desktop app for system tray + global shortcuts |
| **Capacitor** | App store distribution, native APIs | Another abstraction layer | Only if app store presence is required |

**PWA features to leverage:**
- Service worker for offline message drafting
- Push notifications (Web Push API)
- Install prompt for home screen
- Background sync for queued messages

### 4.9 Authentication

For a single-user self-hosted system:
- **Local access:** Token-based auth (as Silas already does). Generate a long-lived token on `silas init`.
- **Remote access:** mTLS or WireGuard tunnel. Don't expose WebSocket to the internet without transport security.
- **Multi-device:** Session tokens stored per device. One active WebSocket per device; all receive updates.
- **Always-on:** Tokens don't expire unless revoked. Reconnect silently on network changes.

### 4.10 Offline

| Feature | Offline Behavior |
|---------|-----------------|
| **View history** | ✅ Cached in IndexedDB |
| **Draft messages** | ✅ Stored locally, sent on reconnect |
| **View tasks** | ✅ Last-known state cached |
| **New AI interactions** | ❌ Requires server |
| **Approvals** | ❌ Requires server (security critical) |

### 4.11 Performance

| Concern | Solution |
|---------|----------|
| **Long message lists** | Virtual scrolling (svelte-virtual-scroll or custom). Only render visible messages + buffer. |
| **Streaming text** | Append to DOM incrementally. Don't re-render entire message on each token. |
| **Large code blocks** | Lazy syntax highlighting (highlight on scroll into view) |
| **Images** | Lazy loading with blur-up placeholders |
| **Search** | Client-side index (FlexSearch) for recent messages; server-side for full history |
| **Bundle size** | Code splitting per route. Main chat bundle < 100KB gzipped. |

### 4.12 Deployment

**Self-hosted first.** This is a personal AI agent — it should run on user's hardware.

| Option | Setup | Use Case |
|--------|-------|----------|
| **Docker Compose** | `docker compose up` — single command | Primary deployment: Silas + UI + PostgreSQL |
| **Bare metal** | `pip install silas` + systemd service | Advanced users, existing servers |
| **Cloud VM** | Docker on a VPS | Remote access, always-on |

---

## 5. Recommended Stack

| Layer | Choice | Justification |
|-------|--------|---------------|
| **Database** | PostgreSQL 16 + pgvector (or SQLite for MVP) | Proven, extensible, handles all data patterns. SQLite fine to start. |
| **Backend** | FastAPI (Python 3.13+) | Already the Silas runtime. One codebase, one language. |
| **Real-time** | WebSocket (primary) + WebRTC (voice/video) | Bidirectional for chat, low-latency for media |
| **Frontend** | SvelteKit + Svelte 5 | Best DX/performance ratio for a small team. Runes reactivity is excellent. |
| **UI components** | shadcn-svelte (built on Bits UI/Melt UI) | Full source ownership, accessible, customizable |
| **Styling** | Tailwind CSS 4 | Utility-first, works perfectly with shadcn-svelte |
| **Icons** | Lucide | Clean, consistent, extensive |
| **Fonts** | Inter + JetBrains Mono | Industry standard pairing |
| **Bundler** | Vite (via SvelteKit) | No competition for this stack |
| **Mobile** | PWA (phase 1) → Tauri v2 (phase 2) | Ship fast with PWA, add native features later |
| **Deployment** | Docker Compose | Single-command setup |

---

## 6. Build Order

### Phase 1: Core Chat (Weeks 1-3)

**Goal:** Replace the current static PWA with a real chat interface.

1. **SvelteKit project setup** with shadcn-svelte, Tailwind, Inter/JetBrains Mono fonts
2. **WebSocket connection** to existing Silas backend
3. **Chat interface** — message list with virtual scrolling, streaming text rendering, input bar
4. **Message rendering** — Markdown (with GFM tables, code highlighting, images)
5. **Basic dark theme** following the color system above
6. **Responsive layout** — desktop two-panel (sidebar + chat), mobile single-column

**Deliverable:** A functional chat that replaces `web/index.html` with dramatically better UX.

### Phase 2: Delegation & Control (Weeks 4-6)

**Goal:** Expose Silas's approval/task system through proper UI.

1. **Approval cards** — inline approve/deny/edit for pending actions
2. **Task cards** — work item status, progress bars, expandable sub-tasks
3. **Notification system** — toast notifications, unread badges
4. **Conversation history** — sidebar list, search, persistence
5. **Settings panel** — tool permissions, standing approvals, budget limits

**Deliverable:** Users can delegate tasks, approve actions, and monitor progress.

### Phase 3: Workbench (Weeks 7-10)

**Goal:** Move beyond chat into structured work.

1. **Canvas panel** — split view with document/code editor alongside chat
2. **File browser** — tree view of workspace files
3. **Dashboard** — active tasks, cost tracking, system health
4. **Memory browser** — view/edit/delete AI memories
5. **Audit log viewer** — collapsible activity timeline

**Deliverable:** Full workbench experience for power users.

### Phase 4: Multimodal (Weeks 11-14)

**Goal:** Voice and visual interaction.

1. **Voice mode** — push-to-talk, real-time transcription, AI voice output
2. **Screen sharing** — capture and share screen context with AI
3. **Image/file handling** — drag-drop upload, inline preview, AI analysis
4. **PWA enhancements** — push notifications, offline drafts, install prompt

**Deliverable:** Multimodal interaction across desktop and mobile.

### Phase 5: Polish & Native (Weeks 15+)

1. **Light mode** theme
2. **Conversation branching** — fork at any message
3. **Keyboard shortcuts** — Raycast-style command palette (⌘+K)
4. **Tauri desktop wrapper** — system tray, global shortcuts
5. **Sound design** — notification chimes, voice mode indicators
6. **Onboarding flow** — progressive disclosure for new users
7. **Performance optimization** — bundle analysis, lazy loading, caching strategies

---

## Appendix: Key References

| Resource | URL | Key Takeaway |
|----------|-----|-------------|
| Google PAIR Guidebook | https://pair.withgoogle.com/guidebook/ | Trust calibration, mental models, human-AI collaboration patterns |
| Microsoft HAX Toolkit | https://aka.ms/haxtoolkit/ | 18 guidelines for human-AI interaction |
| Microsoft Copilot UX Guidance | https://learn.microsoft.com/en-us/microsoft-cloud/dev/copilot/isv/ux-guidance | Immersive/Assistive/Embedded frameworks, foundational principles |
| Linear "Design for the AI Age" | https://linear.app/now/design-for-the-ai-age | Workbench metaphor, form follows function, chat is a weak form |
| shadcn-svelte | https://shadcn-svelte.com/ | Component library for Svelte 5 |
| assistant-ui (React) | https://github.com/assistant-ui/assistant-ui | Reference for AI chat UI patterns (streaming, tool calls, approvals) |
| Vercel AI SDK | https://ai-sdk.dev/ | Streaming patterns, chat hooks, multi-provider support |
| Lucide Icons | https://lucide.dev/ | Icon library |
| Inter Font | https://rsms.me/inter/ | UI typeface |
| JetBrains Mono | https://www.jetbrains.com/lp/mono/ | Monospace typeface |
