<script lang="ts">
	/**
	 * IosInstallBanner — Shows iOS Home Screen add prompt.
	 * Only shown when: iOS Safari + not already installed.
	 */
	import { dismissIosPrompt } from '$lib/stores/notifications';

	let {
		ondismiss,
	}: {
		ondismiss?: () => void;
	} = $props();
</script>

<div class="fixed bottom-0 left-0 right-0 z-50 pb-safe">
	<div class="mx-3 mb-3 rounded-2xl border border-zinc-700 bg-zinc-900/95 p-4 backdrop-blur-xl shadow-2xl">
		<div class="flex items-start gap-3">
			<img src="/icons/icon-192.png" alt="Autopoiesis" class="h-12 w-12 rounded-2xl shrink-0" />
			<div class="flex-1 min-w-0">
				<p class="text-sm font-semibold text-zinc-100">Add to Home Screen</p>
				<p class="mt-0.5 text-xs text-zinc-400 leading-relaxed">
					Tap <strong>Share</strong> then <strong>"Add to Home Screen"</strong> for the best experience
				</p>
			</div>
			<button
				class="shrink-0 text-zinc-500 hover:text-zinc-300 p-1"
				onclick={() => {
					dismissIosPrompt();
					ondismiss?.();
				}}
				aria-label="Dismiss"
			>
				✕
			</button>
		</div>
	</div>
</div>
