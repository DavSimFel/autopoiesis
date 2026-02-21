<script lang="ts">
	/**
	 * T2Summary — Tier-2 agent run summary
	 *
	 * "Trust but verify" pattern:
	 *  - Default view: human-readable summary + bullet points
	 *  - Toggle: raw log stream for full transparency
	 */
	import type { UIEvent, T2SummaryData, LogEntry } from '$lib/types';
	import { formatRelativeTime, formatDuration } from '$lib/utils';

	let {
		event,
	}: {
		event: UIEvent<T2SummaryData>;
	} = $props();

	const d = $derived(event.data);
	let showRawLogs = $state(false);

	const logLevelColor: Record<LogEntry['level'], string> = {
		debug: 'text-zinc-500',
		info: 'text-zinc-400',
		warn: 'text-amber-400',
		error: 'text-red-400',
	};

	const hasDuration = $derived(d.duration !== undefined);
	const hasLogs = $derived(d.rawLogs && d.rawLogs.length > 0);
</script>

<div class="rounded-xl border border-zinc-800 bg-zinc-900/60 p-4 backdrop-blur-sm">
	<!-- Header -->
	<div class="mb-3 flex items-start justify-between gap-3">
		<div class="min-w-0 flex-1">
			<div class="flex items-center gap-2">
				<span class="text-zinc-500 text-sm">⚡</span>
				<h3 class="text-sm font-semibold text-zinc-100 truncate">{d.title}</h3>
			</div>
			<div class="mt-1 flex gap-3 text-[10px] text-zinc-500 flex-wrap">
				{#if d.tasksCompleted !== undefined}
					<span>{d.tasksCompleted} tasks</span>
				{/if}
				{#if hasDuration}
					<span>{formatDuration(d.duration!)}</span>
				{/if}
				{#if d.completedAt}
					<span>{formatRelativeTime(d.completedAt)}</span>
				{/if}
			</div>
		</div>

		<!-- Raw logs toggle — "trust but verify" -->
		{#if hasLogs}
			<button
				class="shrink-0 rounded-lg border border-zinc-700 px-2 py-1 text-[10px] text-zinc-400
					hover:border-zinc-600 hover:text-zinc-300 transition-colors"
				onclick={() => (showRawLogs = !showRawLogs)}
				title="Toggle raw logs"
			>
				{showRawLogs ? '📄 summary' : '🔍 raw logs'}
			</button>
		{/if}
	</div>

	<!-- Tools used badges -->
	{#if d.toolsUsed && d.toolsUsed.length > 0}
		<div class="mb-3 flex flex-wrap gap-1">
			{#each d.toolsUsed as tool}
				<span class="rounded bg-zinc-800 px-1.5 py-0.5 font-mono text-[10px] text-zinc-500">
					{tool}
				</span>
			{/each}
		</div>
	{/if}

	<!-- Summary view -->
	{#if !showRawLogs}
		<p class="text-sm text-zinc-300 leading-relaxed">{d.summary}</p>

		{#if d.bulletPoints && d.bulletPoints.length > 0}
			<ul class="mt-3 space-y-1.5">
				{#each d.bulletPoints as point}
					<li class="flex items-start gap-2 text-sm text-zinc-400">
						<span class="mt-0.5 shrink-0 text-zinc-600">•</span>
						<span>{point}</span>
					</li>
				{/each}
			</ul>
		{/if}
	{:else}
		<!-- Raw log view -->
		<div class="max-h-80 overflow-y-auto rounded-lg bg-zinc-950 p-3 font-mono text-xs">
			{#each d.rawLogs! as entry (entry.ts)}
				<div class="flex gap-2 py-0.5 leading-relaxed">
					<span class="shrink-0 text-zinc-600">{new Date(entry.ts).toISOString().split('T')[1].replace('Z','')}</span>
					<span class="shrink-0 w-10 {logLevelColor[entry.level]}">{entry.level.toUpperCase()}</span>
					{#if entry.tool}
						<span class="shrink-0 text-violet-500">[{entry.tool}]</span>
					{/if}
					<span class="{logLevelColor[entry.level]} break-all">{entry.msg}</span>
				</div>
				{#if entry.data}
					<div class="ml-24 pb-1 text-zinc-600 break-all">
						{JSON.stringify(entry.data)}
					</div>
				{/if}
			{/each}
		</div>
		<p class="mt-1 text-right text-[10px] text-zinc-600">{d.rawLogs!.length} log entries</p>
	{/if}
</div>
