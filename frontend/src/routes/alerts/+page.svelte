<script lang="ts">
	/**
	 * Alerts — notification settings + governance display.
	 * Shows: notification status, daily push quota, quiet hours,
	 * and lets user grant/revoke permission.
	 */
	import { notificationState, requestPermission, dismissIosPrompt } from '$lib/stores/notifications';

	const QUIET_START = 23;
	const QUIET_END = 8;
	const MAX_DAILY = 5;

	async function handleGrantPermission() {
		await requestPermission();
	}

	function cetHour(): number {
		return (new Date().getUTCHours() + 1) % 24;
	}

	const currentHour = $derived(cetHour());
	const isQuiet = $derived(currentHour >= QUIET_START || currentHour < QUIET_END);
</script>

<svelte:head>
	<title>Alerts · Autopoiesis</title>
</svelte:head>

<div class="mx-auto max-w-md px-4 py-6 space-y-6">
	<div>
		<h1 class="text-base font-semibold text-zinc-100">Notification Settings</h1>
		<p class="mt-1 text-sm text-zinc-500">Push alerts are governed to protect your focus.</p>
	</div>

	<!-- Permission status -->
	<div class="rounded-xl border border-zinc-800 bg-zinc-900/60 p-4 space-y-3">
		<h2 class="text-xs font-semibold uppercase tracking-wider text-zinc-600">Permission</h2>

		<div class="flex items-center justify-between">
			<div>
				<div class="text-sm text-zinc-300">
					{$notificationState.granted ? '✓ Notifications enabled' : 'Notifications disabled'}
				</div>
				{#if !$notificationState.granted}
					<div class="mt-0.5 text-xs text-zinc-600">Enable to receive push alerts</div>
				{/if}
			</div>
			{#if !$notificationState.granted}
				<button
					class="rounded-lg bg-zinc-100 px-3 py-1.5 text-sm font-semibold text-zinc-900
						hover:bg-zinc-200 transition-colors"
					onclick={handleGrantPermission}
				>
					Enable
				</button>
			{/if}
		</div>
	</div>

	<!-- Governance rules -->
	<div class="rounded-xl border border-zinc-800 bg-zinc-900/60 p-4 space-y-4">
		<h2 class="text-xs font-semibold uppercase tracking-wider text-zinc-600">Governance Rules</h2>

		<!-- Daily quota -->
		<div>
			<div class="mb-1.5 flex items-center justify-between">
				<span class="text-sm text-zinc-300">Daily push quota</span>
				<span class="text-sm text-zinc-100 font-semibold">
					{$notificationState.dailyCount} / {MAX_DAILY}
				</span>
			</div>
			<div class="h-2 rounded-full bg-zinc-800 overflow-hidden">
				<div
					class="h-full rounded-full transition-all
						{$notificationState.dailyCount >= MAX_DAILY ? 'bg-red-500' : 'bg-emerald-500'}"
					style="width: {Math.min(($notificationState.dailyCount / MAX_DAILY) * 100, 100)}%"
				></div>
			</div>
			{#if $notificationState.dailyCount >= MAX_DAILY}
				<p class="mt-1 text-xs text-red-400">Daily limit reached — resets at midnight</p>
			{/if}
		</div>

		<!-- Quiet hours -->
		<div class="flex items-start justify-between">
			<div>
				<div class="text-sm text-zinc-300">Quiet hours</div>
				<div class="mt-0.5 text-xs text-zinc-600">No push notifications during quiet hours</div>
			</div>
			<div class="text-right">
				<div class="text-sm font-semibold text-zinc-100">23:00 – 08:00 CET</div>
				<div class="mt-0.5 text-xs {isQuiet ? 'text-amber-400' : 'text-zinc-600'}">
					{isQuiet ? '🌙 Currently quiet' : '☀️ Active hours'}
				</div>
			</div>
		</div>

		<!-- Reset time -->
		<div class="flex items-center justify-between">
			<div class="text-sm text-zinc-300">Quota resets</div>
			<div class="text-sm text-zinc-500">Daily at midnight</div>
		</div>
	</div>

	<!-- Notification types (informational) -->
	<div class="rounded-xl border border-zinc-800 bg-zinc-900/60 p-4 space-y-3">
		<h2 class="text-xs font-semibold uppercase tracking-wider text-zinc-600">When you'll be notified</h2>
		<ul class="space-y-2">
			{#each [
				{ icon: '⚠️', label: 'Critical risk approvals pending' },
				{ icon: '✅', label: 'Long-running tasks completed' },
				{ icon: '💬', label: 'Agent needs your input' },
				{ icon: '🔥', label: 'High-priority action required' },
			] as item}
				<li class="flex items-center gap-2.5 text-sm text-zinc-400">
					<span class="text-base">{item.icon}</span>
					{item.label}
				</li>
			{/each}
		</ul>
	</div>
</div>
