<script lang="ts">
	import { onMount } from 'svelte';
	import { getStatus } from '$lib/api-client';
	import { streamEvents } from '$lib/stores/active-state';
	import EventRenderer from '$lib/components/EventRenderer.svelte';
	import AgentStatus from '$lib/components/AgentStatus.svelte';
	import type { AgentStatusData, UIEvent } from '$lib/types';

	function asRecord(value: unknown): Record<string, unknown> {
		return typeof value === 'object' && value !== null ? (value as Record<string, unknown>) : {};
	}

	function asString(value: unknown, fallback: string): string {
		return typeof value === 'string' && value.length > 0 ? value : fallback;
	}

	function asNumber(value: unknown): number {
		return typeof value === 'number' && Number.isFinite(value) ? value : 0;
	}

	function asStatus(value: unknown): AgentStatusData['status'] {
		if (value === 'healthy' || value === 'degraded' || value === 'offline' || value === 'busy') {
			return value;
		}
		return 'offline';
	}

	function toAgentStatusEvent(payload: unknown): UIEvent<AgentStatusData> {
		const now = new Date().toISOString();
		const data = asRecord(payload);
		const agentId = asString(data.agentId, 'autopoiesis-agent');
		const statusData: AgentStatusData = {
			agentId,
			name: asString(data.name, 'Autopoiesis'),
			status: asStatus(data.status),
			pendingApprovals: asNumber(data.pendingApprovals),
			activeTasks: asNumber(data.activeTasks),
			queueDepth: asNumber(data.queueDepth),
			lastSeen: asString(data.lastSeen, now),
			uptime: typeof data.uptime === 'string' ? data.uptime : undefined,
		};

		return {
			type: 'agent-status',
			data: statusData,
			meta: {
				id: `status-${agentId}`,
				mode: 'stream',
				priority: 1,
				ephemeral: true,
				resolvable: false,
				timestamp: now,
			},
		};
	}

	const fallbackStatus = toAgentStatusEvent({
		agentId: 'autopoiesis-agent',
		name: 'Autopoiesis',
		status: 'offline',
		lastSeen: new Date().toISOString(),
	});

	let statusEvent = $state<UIEvent<AgentStatusData>>(fallbackStatus);

	const latestStatusFromStream = $derived(
		$streamEvents.find((event) => event.type === 'agent-status') as UIEvent<AgentStatusData> | undefined,
	);

	$effect(() => {
		if (latestStatusFromStream) {
			statusEvent = latestStatusFromStream;
		}
	});

	onMount(async () => {
		try {
			const status = await getStatus();
			statusEvent = toAgentStatusEvent(status);
		} catch {
			// Keep the fallback card when /api/status is unavailable.
		}
	});
</script>

<svelte:head>
	<title>Home · Autopoiesis</title>
</svelte:head>

<div class="mx-auto max-w-2xl px-3 py-4 space-y-4">
	<section class="space-y-2">
		<h1 class="text-base font-semibold text-zinc-100">Home</h1>
		<AgentStatus event={statusEvent} />
	</section>

	<section class="space-y-3">
		<div class="px-1 text-[10px] font-semibold uppercase tracking-wider text-zinc-600">Live feed</div>
		{#if $streamEvents.length === 0}
			<div class="flex flex-col items-center justify-center py-16 text-center">
				<div class="mb-3 text-4xl opacity-20">⚡</div>
				<p class="text-sm text-zinc-600">Waiting for events…</p>
				<p class="mt-1 text-xs text-zinc-700">The agent will push updates here in real time</p>
			</div>
		{:else}
			{#each $streamEvents as event (event.meta.id)}
				<article class="relative">
					{#if event.meta.priority <= 2}
						<div class="absolute -left-1 top-0 bottom-0 w-0.5 rounded-full bg-amber-500/60"></div>
					{/if}
					<EventRenderer {event} />
				</article>
			{/each}
		{/if}
	</section>
</div>
