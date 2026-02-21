<script lang="ts">
	/**
	 * Chat — direct chat with the agent via MCP tool calls.
	 */
	import { callTool } from '$lib/api-client';
	import { streamEvents } from '$lib/stores/active-state';
	import EventRenderer from '$lib/components/EventRenderer.svelte';
	import type { UIEvent, ChatMessageData } from '$lib/types';

	let input = $state('');
	let sending = $state(false);
	let error = $state<string | null>(null);

	// Local optimistic messages — cast to base UIEvent for EventRenderer compatibility
	let localMessages = $state<UIEvent[]>([]);

	// Chat messages from stream
	const chatEvents = $derived(
		$streamEvents.filter((e) => e.type === 'chat-message'),
	);

	const allMessages = $derived(
		[...chatEvents, ...localMessages].sort(
			(a, b) => new Date(a.meta.timestamp).getTime() - new Date(b.meta.timestamp).getTime(),
		),
	);

	let messagesEl = $state<HTMLDivElement | null>(null);

	$effect(() => {
		// Auto-scroll to bottom on new messages
		void allMessages;
		if (messagesEl) {
			messagesEl.scrollTop = messagesEl.scrollHeight;
		}
	});

	async function send() {
		const text = input.trim();
		if (!text || sending) return;

		const id = crypto.randomUUID();
		const ts = new Date().toISOString();

		// Optimistic user message
		const userMsg: UIEvent = {
			type: 'chat-message',
			data: {
				messageId: id,
				role: 'user',
				content: text,
				timestamp: ts,
			},
			meta: {
				id,
				mode: 'stream',
				priority: 5,
				ephemeral: true,
				resolvable: false,
				timestamp: ts,
			},
		};
		localMessages = [...localMessages, userMsg];
		input = '';
		sending = true;
		error = null;

		try {
			await callTool('agent_chat', { message: text });
			// Response will come via SSE → stream
		} catch (e) {
			error = e instanceof Error ? e.message : 'Send failed';
		} finally {
			sending = false;
		}
	}
</script>

<svelte:head>
	<title>Chat · Autopoiesis</title>
</svelte:head>

<div class="flex h-full flex-col overflow-hidden">
	<!-- Messages -->
	<div
		bind:this={messagesEl}
		class="flex-1 overflow-y-auto p-4 space-y-3 pb-2"
	>
		{#each allMessages as event (event.meta.id)}
			<EventRenderer {event} focusable={false} />
		{:else}
			<div class="flex flex-col items-center justify-center py-16 text-center">
				<div class="mb-3 text-4xl opacity-20">💬</div>
				<p class="text-sm text-zinc-600">Start a conversation</p>
			</div>
		{/each}

		{#if sending}
			<div class="flex items-center gap-2 pl-9">
				<div class="rounded-2xl bg-zinc-800 px-3 py-2">
					<span class="inline-flex gap-1">
						<span class="h-1.5 w-1.5 animate-bounce rounded-full bg-zinc-500 [animation-delay:0ms]"></span>
						<span class="h-1.5 w-1.5 animate-bounce rounded-full bg-zinc-500 [animation-delay:150ms]"></span>
						<span class="h-1.5 w-1.5 animate-bounce rounded-full bg-zinc-500 [animation-delay:300ms]"></span>
					</span>
				</div>
			</div>
		{/if}
	</div>

	<!-- Error -->
	{#if error}
		<div class="mx-4 mb-2 rounded-lg border border-red-800/40 bg-red-900/20 p-2 text-sm text-red-400">
			{error}
		</div>
	{/if}

	<!-- Input -->
	<div class="shrink-0 border-t border-zinc-800 bg-zinc-950 p-3 pb-safe">
		<form
			class="flex items-end gap-2"
			onsubmit={(e) => { e.preventDefault(); send(); }}
		>
			<textarea
				bind:value={input}
				placeholder="Message the agent…"
				rows={1}
				class="flex-1 resize-none rounded-xl border border-zinc-700 bg-zinc-900 px-3 py-2.5 text-sm
					text-zinc-100 placeholder:text-zinc-600 focus:border-zinc-500 focus:outline-none
					focus:ring-1 focus:ring-zinc-500 max-h-32"
				onkeydown={(e) => {
					if (e.key === 'Enter' && !e.shiftKey) {
						e.preventDefault();
						send();
					}
				}}
			></textarea>
			<button
				type="submit"
				class="shrink-0 rounded-xl bg-zinc-100 px-4 py-2.5 text-sm font-semibold text-zinc-900
					hover:bg-zinc-200 active:bg-zinc-300 disabled:opacity-50 transition-colors"
				disabled={sending || !input.trim()}
			>
				↑
			</button>
		</form>
	</div>
</div>
