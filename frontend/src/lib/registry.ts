/**
 * Component Registry
 *
 * Maps UIEvent `type` string → Svelte component.
 * Unknown types fall back to FallbackCard (formatted JSON).
 *
 * Add new component mappings here as the server grows new event types.
 */

import type { Component } from 'svelte';
import AgentStatus from '$lib/components/AgentStatus.svelte';
import ActionCard from '$lib/components/ActionCard.svelte';
import ApprovalItem from '$lib/components/ApprovalItem.svelte';
import ApprovalQueue from '$lib/components/ApprovalQueue.svelte';
import T2Summary from '$lib/components/T2Summary.svelte';
import ChatMessage from '$lib/components/ChatMessage.svelte';
import ToolCallCard from '$lib/components/ToolCallCard.svelte';
import MorningBriefing from '$lib/components/MorningBriefing.svelte';
import FallbackCard from '$lib/components/FallbackCard.svelte';

// ---------------------------------------------------------------
// Type alias: all renderable components receive { event: UIEvent }
// ---------------------------------------------------------------

export type RegistryComponent = Component<{ event: unknown; onresolve?: (id: string) => void }>;

export const registry: Record<string, RegistryComponent> = {
	// Agent health / status
	'agent-status': AgentStatus as unknown as RegistryComponent,
	agent_status: AgentStatus as unknown as RegistryComponent,

	// Generic action card with buttons
	'action-card': ActionCard as unknown as RegistryComponent,
	action_card: ActionCard as unknown as RegistryComponent,

	// Single approval request
	'approval-item': ApprovalItem as unknown as RegistryComponent,
	approval_item: ApprovalItem as unknown as RegistryComponent,

	// List of approval requests
	'approval-queue': ApprovalQueue as unknown as RegistryComponent,
	approval_queue: ApprovalQueue as unknown as RegistryComponent,

	// T2 (tier-2) agent run summary with raw log toggle
	't2-summary': T2Summary as unknown as RegistryComponent,
	t2_summary: T2Summary as unknown as RegistryComponent,

	// Chat message bubble
	'chat-message': ChatMessage as unknown as RegistryComponent,
	chat_message: ChatMessage as unknown as RegistryComponent,

	// Inline tool execution display
	'tool-call': ToolCallCard as unknown as RegistryComponent,
	tool_call: ToolCallCard as unknown as RegistryComponent,

	// Composed morning status card
	'morning-briefing': MorningBriefing as unknown as RegistryComponent,
	morning_briefing: MorningBriefing as unknown as RegistryComponent,
};

/** Resolve a type string to its component, falling back to FallbackCard */
export function resolve(type: string): RegistryComponent {
	return (registry[type] ?? FallbackCard) as RegistryComponent;
}
