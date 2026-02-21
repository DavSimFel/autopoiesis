// ============================================================
// Core Data Contract — server returns JSON only, shell renders
// ============================================================

export interface UIEventMeta {
	id: string;
	mode: 'stream' | 'focus';
	priority: number;
	/** If true, lives in Active State until explicitly resolved */
	ephemeral: boolean;
	resolvable: boolean;
	resolved?: boolean;
	resolvedAt?: string;
	badge?: string;
	timestamp: string;
}

export interface UIEvent<T = Record<string, unknown>> {
	type: string; // registry key → Svelte component
	data: T;
	meta: UIEventMeta;
}

// ============================================================
// Component-specific data shapes
// ============================================================

export interface AgentStatusData {
	agentId: string;
	name: string;
	status: 'healthy' | 'degraded' | 'offline' | 'busy';
	pendingApprovals: number;
	activeTasks: number;
	queueDepth: number;
	lastSeen: string;
	uptime?: string;
}

export interface ActionCardData {
	title: string;
	description?: string;
	icon?: string;
	actions: ActionButton[];
	/** Optional structured payload to show */
	payload?: Record<string, unknown>;
}

export interface ActionButton {
	label: string;
	variant: 'primary' | 'secondary' | 'destructive' | 'ghost';
	tool: string; // MCP tool name to call
	args?: Record<string, unknown>;
	confirm?: string; // confirmation prompt text
}

export interface ApprovalItemData {
	approvalId: string;
	title: string;
	description: string;
	requestedBy: string;
	requestedAt: string;
	risk: 'low' | 'medium' | 'high' | 'critical';
	details?: Record<string, unknown>;
	tool?: string;
	args?: Record<string, unknown>;
	timeoutAt?: string;
}

export interface ApprovalQueueData {
	items: ApprovalItemData[];
	totalPending: number;
}

export interface T2SummaryData {
	title: string;
	summary: string;
	bulletPoints?: string[];
	rawLogs?: LogEntry[];
	duration?: number;
	tasksCompleted?: number;
	toolsUsed?: string[];
	startedAt: string;
	completedAt?: string;
}

export interface LogEntry {
	ts: string;
	level: 'debug' | 'info' | 'warn' | 'error';
	msg: string;
	tool?: string;
	data?: unknown;
}

export interface ChatMessageData {
	messageId: string;
	role: 'user' | 'assistant' | 'system' | 'tool';
	content: string;
	agentId?: string;
	agentName?: string;
	toolName?: string;
	timestamp: string;
	streaming?: boolean;
}

export interface ToolCallData {
	callId: string;
	toolName: string;
	args: Record<string, unknown>;
	result?: unknown;
	error?: string;
	status: 'pending' | 'running' | 'success' | 'error';
	duration?: number;
	startedAt: string;
}

export interface MorningBriefingData {
	date: string;
	greeting: string;
	agentStatus: AgentStatusData;
	summary?: T2SummaryData;
	topActions?: ActionCardData[];
	pendingApprovals?: number;
	highlights?: string[];
}

// ============================================================
// SSE push notification from /mcp/sse
// ============================================================

export interface UINotification {
	event: 'ui_event' | 'ping' | 'connected';
	data: UIEvent | null;
	timestamp: string;
}

// ============================================================
// Skill (for More page — deterministic override listing)
// ============================================================

export interface Skill {
	name: string;
	description: string;
	tool: string;
	args?: Record<string, unknown>;
	category?: string;
	dangerous?: boolean;
}

// ============================================================
// Navigation
// ============================================================

export type NavTab = 'chat' | 'active' | 'stream' | 'alerts' | 'more';

export interface NavItem {
	id: NavTab;
	label: string;
	icon: string;
	badge?: number;
}
