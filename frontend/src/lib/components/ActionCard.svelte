<script lang="ts">
	import type { UIEvent, ActionCardData } from '$lib/types';
	import { callTool } from '$lib/api-client';
	import { resolveEvent } from '$lib/stores/active-state';
	import { formatRelativeTime } from '$lib/utils';

	let {
		event,
		onresolve,
	}: {
		event: UIEvent<ActionCardData>;
		onresolve?: (id: string) => void;
	} = $props();

	const d = $derived(event.data);
	let loading = $state<string | null>(null); // which button is loading
	let error = $state<string | null>(null);
	let confirmTarget = $state<string | null>(null); // button label awaiting confirm

	async function handleAction(label: string, tool: string, args: Record<string, unknown> = {}, confirm?: string) {
		if (confirm && confirmTarget !== label) {
			confirmTarget = label;
			return;
		}
		confirmTarget = null;
		loading = label;
		error = null;
		try {
			await callTool(tool, args);
			if (event.meta.resolvable) {
				resolveEvent(event.meta.id);
				onresolve?.(event.meta.id);
			}
		} catch (e) {
			error = e instanceof Error ? e.message : 'Action failed';
		} finally {
			loading = null;
		}
	}

	const variantClass: Record<string, string> = {
		primary:
			'bg-zinc-100 text-zinc-900 hover:bg-zinc-200 active:bg-zinc-300',
		secondary:
			'bg-zinc-800 text-zinc-100 hover:bg-zinc-700 border border-zinc-700',
		destructive:
			'bg-red-900/30 text-red-400 hover:bg-red-900/50 border border-red-800/40',
		ghost:
			'text-zinc-400 hover:text-zinc-100 hover:bg-zinc-800',
	};
</script>

<div class="rounded-xl border border-zinc-800 bg-zinc-900/60 p-4 backdrop-blur-sm">
	<!-- Header -->
	<div class="mb-3 flex items-start gap-3">
		{#if d.icon}
			<span class="text-2xl">{d.icon}</span>
		{/if}
		<div class="min-w-0 flex-1">
			<h3 class="text-sm font-semibold text-zinc-100">{d.title}</h3>
			{#if d.description}
				<p class="mt-0.5 text-sm text-zinc-400">{d.description}</p>
			{/if}
		</div>
		{#if event.meta.badge}
			<span class="shrink-0 rounded-full bg-zinc-800 px-2 py-0.5 text-[10px] text-zinc-400">
				{event.meta.badge}
			</span>
		{/if}
	</div>

	<!-- Optional payload preview -->
	{#if d.payload}
		<div class="mb-3 overflow-auto rounded-lg bg-zinc-950 p-3">
			<pre class="text-xs text-zinc-400">{JSON.stringify(d.payload, null, 2)}</pre>
		</div>
	{/if}

	<!-- Error -->
	{#if error}
		<div class="mb-3 rounded-lg border border-red-800/40 bg-red-900/20 p-2 text-sm text-red-400">
			{error}
		</div>
	{/if}

	<!-- Actions -->
	<div class="flex flex-wrap gap-2">
		{#each d.actions as action (action.label)}
			<button
				class="rounded-lg px-3 py-1.5 text-sm font-medium transition-colors disabled:opacity-50
					{variantClass[action.variant] ?? variantClass.secondary}"
				disabled={loading !== null}
				onclick={() => handleAction(action.label, action.tool, action.args ?? {}, action.confirm)}
			>
				{#if loading === action.label}
					<span class="inline-block h-3 w-3 animate-spin rounded-full border-2 border-current border-t-transparent"></span>
				{:else if confirmTarget === action.label}
					Confirm?
				{:else}
					{action.label}
				{/if}
			</button>
		{/each}
	</div>

	<!-- Timestamp -->
	<div class="mt-3 text-right text-[10px] text-zinc-600">
		{formatRelativeTime(event.meta.timestamp)}
	</div>
</div>
