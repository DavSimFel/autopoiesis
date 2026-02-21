<script lang="ts">
	import type { UIEvent, ApprovalItemData } from '$lib/types';
	import { callTool } from '$lib/mcp-client';
	import { resolveEvent } from '$lib/stores/active-state';
	import { formatRelativeTime, riskColor, riskBg } from '$lib/utils';

	let {
		event,
		onresolve,
		compact = false,
	}: {
		event: UIEvent<ApprovalItemData>;
		onresolve?: (id: string) => void;
		compact?: boolean;
	} = $props();

	const d = $derived(event.data);
	let loading = $state<'approve' | 'reject' | null>(null);
	let error = $state<string | null>(null);
	let detailsOpen = $state(false);

	// Countdown timer for timeout
	let timeoutRemaining = $state<string | null>(null);
	$effect(() => {
		if (!d.timeoutAt) return;
		const update = () => {
			const remaining = new Date(d.timeoutAt!).getTime() - Date.now();
			if (remaining <= 0) {
				timeoutRemaining = 'Expired';
				return;
			}
			const s = Math.floor(remaining / 1_000);
			const m = Math.floor(s / 60);
			const h = Math.floor(m / 60);
			if (h > 0) timeoutRemaining = `${h}h ${m % 60}m`;
			else if (m > 0) timeoutRemaining = `${m}m ${s % 60}s`;
			else timeoutRemaining = `${s}s`;
		};
		update();
		const interval = setInterval(update, 1_000);
		return () => clearInterval(interval);
	});

	async function decide(action: 'approve' | 'reject') {
		loading = action;
		error = null;
		try {
			await callTool(`agent_approval_${action}`, {
				approval_id: d.approvalId,
			});
			resolveEvent(event.meta.id);
			onresolve?.(event.meta.id);
		} catch (e) {
			error = e instanceof Error ? e.message : 'Action failed';
		} finally {
			loading = null;
		}
	}
</script>

<div class="rounded-xl border {riskBg(d.risk)} p-4 backdrop-blur-sm transition-all">
	<!-- Risk badge + header -->
	<div class="mb-2 flex items-start gap-3">
		<div class="flex-1 min-w-0">
			<div class="flex items-center gap-2 flex-wrap">
				<span class="text-[10px] font-bold uppercase tracking-wider {riskColor(d.risk)}">
					{d.risk} risk
				</span>
				{#if timeoutRemaining}
					<span class="text-[10px] text-zinc-500">
						⏱ {timeoutRemaining}
					</span>
				{/if}
			</div>
			<h3 class="mt-0.5 text-sm font-semibold text-zinc-100 leading-snug">
				{d.title}
			</h3>
		</div>
	</div>

	<!-- Description -->
	<p class="mb-3 text-sm text-zinc-400 leading-relaxed">
		{d.description}
	</p>

	<!-- Meta -->
	{#if !compact}
		<div class="mb-3 flex gap-4 text-xs text-zinc-500">
			<span>By: <span class="text-zinc-400">{d.requestedBy}</span></span>
			<span>{formatRelativeTime(d.requestedAt)}</span>
		</div>
	{/if}

	<!-- Tool call preview -->
	{#if d.tool && !compact}
		<button
			class="mb-3 w-full text-left"
			onclick={() => (detailsOpen = !detailsOpen)}
		>
			<div class="flex items-center justify-between rounded-lg bg-zinc-950/50 px-3 py-2 text-xs text-zinc-500 hover:bg-zinc-950">
				<span class="font-mono">{d.tool}()</span>
				<span class="text-[10px]">{detailsOpen ? '▲' : '▼'} details</span>
			</div>
		</button>

		{#if detailsOpen && d.args}
			<div class="mb-3 overflow-auto rounded-lg bg-zinc-950 p-3">
				<pre class="text-xs text-zinc-400">{JSON.stringify(d.args, null, 2)}</pre>
			</div>
		{/if}
	{/if}

	<!-- Error -->
	{#if error}
		<div class="mb-3 rounded-lg border border-red-800/40 bg-red-900/20 p-2 text-sm text-red-400">
			{error}
		</div>
	{/if}

	<!-- Actions -->
	<div class="flex gap-2">
		<button
			class="flex-1 rounded-lg bg-emerald-900/30 py-2 text-sm font-semibold text-emerald-400
				border border-emerald-800/40 hover:bg-emerald-900/50 active:scale-95 transition-all
				disabled:opacity-50"
			disabled={loading !== null}
			onclick={() => decide('approve')}
		>
			{#if loading === 'approve'}
				<span class="inline-block h-3 w-3 animate-spin rounded-full border-2 border-current border-t-transparent"></span>
			{:else}
				✓ Approve
			{/if}
		</button>
		<button
			class="flex-1 rounded-lg bg-red-900/30 py-2 text-sm font-semibold text-red-400
				border border-red-800/40 hover:bg-red-900/50 active:scale-95 transition-all
				disabled:opacity-50"
			disabled={loading !== null}
			onclick={() => decide('reject')}
		>
			{#if loading === 'reject'}
				<span class="inline-block h-3 w-3 animate-spin rounded-full border-2 border-current border-t-transparent"></span>
			{:else}
				✕ Reject
			{/if}
		</button>
	</div>
</div>
