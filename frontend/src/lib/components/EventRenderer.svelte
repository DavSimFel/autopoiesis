<script lang="ts">
	/**
	 * EventRenderer — dynamically resolves UIEvent type → component via registry
	 * and renders it. This is the main rendering primitive of the shell.
	 */
	import { resolve } from '$lib/registry';
	import { resolveEvent } from '$lib/stores/active-state';
	import { openFocus } from '$lib/stores/nav';
	import type { UIEvent } from '$lib/types';

	let {
		event,
		focusable = true,
	}: {
		event: UIEvent;
		focusable?: boolean;
	} = $props();

	const Component = $derived(resolve(event.type));

	function handleResolve(id: string) {
		resolveEvent(id);
	}

	function handleFocus() {
		if (focusable && event.meta.mode === 'focus') {
			openFocus(event);
		}
	}
</script>

{#if focusable && event.meta.mode === 'focus'}
	<button
		class="event-renderer w-full text-left"
		onclick={handleFocus}
		type="button"
	>
		<Component {event} onresolve={handleResolve} />
	</button>
{:else}
	<div class="event-renderer">
		<Component {event} onresolve={handleResolve} />
	</div>
{/if}
