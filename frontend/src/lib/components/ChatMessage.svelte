<script lang="ts">
	import type { UIEvent, ChatMessageData } from '$lib/types';
	import { formatRelativeTime } from '$lib/utils';

	let {
		event,
	}: {
		event: UIEvent<ChatMessageData>;
	} = $props();

	const d = $derived(event.data);
	const isUser = $derived(d.role === 'user');
	const isSystem = $derived(d.role === 'system');
	const isTool = $derived(d.role === 'tool');
</script>

<div class="flex gap-2 {isUser ? 'flex-row-reverse' : 'flex-row'} items-end">
	<!-- Avatar / role indicator -->
	{#if !isUser && !isSystem}
		<div class="mb-1 shrink-0">
			<div class="flex h-7 w-7 items-center justify-center rounded-full
				{isTool ? 'bg-violet-900/50 border border-violet-700' : 'bg-zinc-800 border border-zinc-700'}
				text-sm">
				{isTool ? '🔧' : '🤖'}
			</div>
		</div>
	{/if}

	<div class="max-w-[85%] {isUser ? 'items-end' : 'items-start'} flex flex-col gap-1">
		<!-- Agent name for assistant messages -->
		{#if !isUser && !isSystem && d.agentName}
			<span class="px-1 text-[10px] text-zinc-500">{d.agentName}</span>
		{/if}

		<!-- System message -->
		{#if isSystem}
			<div class="w-full rounded-lg border border-zinc-800/60 bg-zinc-900/40 px-3 py-2 text-center text-xs text-zinc-500 italic">
				{d.content}
			</div>
		{:else}
			<!-- Message bubble -->
			<div
				class="rounded-2xl px-3 py-2 text-sm leading-relaxed
					{isUser
						? 'bg-zinc-100 text-zinc-900 rounded-br-sm'
						: isTool
							? 'bg-violet-950/40 text-zinc-300 border border-violet-800/30 rounded-bl-sm font-mono text-xs'
							: 'bg-zinc-800 text-zinc-100 rounded-bl-sm'}"
			>
				{#if isTool}
					<div class="mb-1 text-[10px] text-violet-400">{d.toolName ?? 'tool'}</div>
				{/if}
				{#if d.streaming}
					{d.content}<span class="ml-0.5 inline-block h-3 w-0.5 animate-pulse bg-current"></span>
				{:else}
					{d.content}
				{/if}
			</div>
		{/if}

		<!-- Timestamp -->
		<span class="px-1 text-[10px] text-zinc-600">
			{formatRelativeTime(d.timestamp)}
		</span>
	</div>
</div>
