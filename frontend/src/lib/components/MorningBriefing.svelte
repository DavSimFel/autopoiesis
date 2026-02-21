<script lang="ts">
	/**
	 * MorningBriefing — Composed card
	 * Renders: greeting + AgentStatus + optional T2Summary + top ActionCards
	 */
	import type { UIEvent, MorningBriefingData } from '$lib/types';

	import AgentStatus from './AgentStatus.svelte';
	import T2Summary from './T2Summary.svelte';
	import ActionCard from './ActionCard.svelte';

	let {
		event,
		onresolve,
	}: {
		event: UIEvent<MorningBriefingData>;
		onresolve?: (id: string) => void;
	} = $props();

	const d = $derived(event.data);

	// Build synthetic UIEvents for child components
	const statusEvent = $derived({
		type: 'agent-status',
		data: d.agentStatus,
		meta: { ...event.meta, id: `${event.meta.id}:status` },
	});

	const summaryEvent = $derived(
		d.summary
			? {
					type: 't2-summary',
					data: d.summary,
					meta: { ...event.meta, id: `${event.meta.id}:summary`, resolvable: false },
				}
			: null,
	);

	function actionEvent(action: import('$lib/types').ActionCardData, i: number) {
		return {
			type: 'action-card',
			data: action,
			meta: { ...event.meta, id: `${event.meta.id}:action:${i}`, resolvable: false },
		};
	}
</script>

<div class="space-y-3">
	<!-- Greeting header -->
	<div class="rounded-xl border border-zinc-800 bg-gradient-to-br from-zinc-900 to-zinc-950 p-4">
		<div class="mb-1 text-[10px] uppercase tracking-widest text-zinc-600">
			{new Date(d.date).toLocaleDateString('en-US', {
				weekday: 'long',
				month: 'long',
				day: 'numeric',
			})}
		</div>
		<h2 class="text-lg font-semibold text-zinc-100">{d.greeting}</h2>

		<!-- Pending approvals alert -->
		{#if d.pendingApprovals && d.pendingApprovals > 0}
			<div class="mt-2 inline-flex items-center gap-1.5 rounded-full bg-amber-900/30 border border-amber-800/40 px-2.5 py-1 text-xs text-amber-400">
				<span class="h-1.5 w-1.5 rounded-full bg-amber-400 animate-pulse"></span>
				{d.pendingApprovals} pending {d.pendingApprovals === 1 ? 'approval' : 'approvals'}
			</div>
		{/if}

		<!-- Highlights -->
		{#if d.highlights && d.highlights.length > 0}
			<ul class="mt-3 space-y-1">
				{#each d.highlights as highlight}
					<li class="flex items-start gap-2 text-sm text-zinc-400">
						<span class="mt-0.5 text-zinc-600">›</span>
						<span>{highlight}</span>
					</li>
				{/each}
			</ul>
		{/if}
	</div>

	<!-- Agent Status -->
	<AgentStatus event={statusEvent} />

	<!-- Yesterday's T2 summary -->
	{#if summaryEvent}
		<T2Summary event={summaryEvent} />
	{/if}

	<!-- Top action cards -->
	{#if d.topActions && d.topActions.length > 0}
		<div class="text-xs font-medium uppercase tracking-wider text-zinc-600 px-1">Suggested Actions</div>
		{#each d.topActions as action, i}
			<ActionCard event={actionEvent(action, i)} {onresolve} />
		{/each}
	{/if}
</div>
