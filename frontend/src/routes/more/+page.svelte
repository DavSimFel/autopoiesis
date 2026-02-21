<script lang="ts">
	/**
	 * More — deterministic override: lists ALL MCP skills alphabetically.
	 * The escape hatch: when the agent doesn't surface something proactively,
	 * you can always find and invoke it here.
	 */
	import { onMount } from 'svelte';
	import { listTools, callTool } from '$lib/mcp-client';
	import type { MCPTool } from '$lib/mcp-client';

	let tools = $state<MCPTool[]>([]);
	let loading = $state(true);
	let error = $state<string | null>(null);
	let search = $state('');
	let invokingTool = $state<string | null>(null);
	let invokeResult = $state<string | null>(null);
	let invokeError = $state<string | null>(null);

	// Selected tool for invocation
	let selectedTool = $state<MCPTool | null>(null);
	let argValues = $state<Record<string, string>>({});

	onMount(async () => {
		try {
			const fetched = await listTools();
			// Sort alphabetically — deterministic listing per spec
			tools = fetched.sort((a, b) => a.name.localeCompare(b.name));
		} catch (e) {
			error = e instanceof Error ? e.message : 'Failed to load tools';
		} finally {
			loading = false;
		}
	});

	const filtered = $derived(
		tools.filter(
			(t) =>
				t.name.toLowerCase().includes(search.toLowerCase()) ||
				(t.description ?? '').toLowerCase().includes(search.toLowerCase()),
		),
	);

	// Group by category prefix (e.g., "email_*", "calendar_*")
	const grouped = $derived(() => {
		const groups: Record<string, MCPTool[]> = {};
		for (const tool of filtered) {
			const parts = tool.name.split('_');
			const category = parts.length > 1 ? parts[0] : 'general';
			if (!groups[category]) groups[category] = [];
			groups[category].push(tool);
		}
		return Object.entries(groups).sort(([a], [b]) => a.localeCompare(b));
	});

	function selectTool(tool: MCPTool) {
		selectedTool = tool;
		argValues = {};
		invokeResult = null;
		invokeError = null;
	}

	async function invoke() {
		if (!selectedTool) return;

		// Parse arg values — try JSON, fall back to string
		const args: Record<string, unknown> = {};
		for (const [key, val] of Object.entries(argValues)) {
			try {
				args[key] = JSON.parse(val);
			} catch {
				args[key] = val;
			}
		}

		invokingTool = selectedTool.name;
		invokeResult = null;
		invokeError = null;

		try {
			const result = await callTool(selectedTool.name, args);
			invokeResult = result.content.map((c) => c.text).join('\n');
		} catch (e) {
			invokeError = e instanceof Error ? e.message : 'Invocation failed';
		} finally {
			invokingTool = null;
		}
	}

	const requiredArgs = $derived(
		selectedTool?.inputSchema?.required ?? [],
	);

	const properties = $derived(
		Object.entries(selectedTool?.inputSchema?.properties ?? {}),
	);
</script>

<svelte:head>
	<title>Skills · Autopoiesis</title>
</svelte:head>

<div class="flex h-full flex-col md:flex-row md:divide-x md:divide-zinc-800 overflow-hidden">
	<!-- Left: Tool list -->
	<div class="flex flex-col md:w-72 md:shrink-0 overflow-hidden">
		<!-- Search bar -->
		<div class="border-b border-zinc-800 p-3">
			<input
				type="search"
				placeholder="Search skills…"
				bind:value={search}
				class="w-full rounded-lg border border-zinc-700 bg-zinc-900 px-3 py-2 text-sm text-zinc-100
					placeholder:text-zinc-600 focus:border-zinc-500 focus:outline-none focus:ring-1 focus:ring-zinc-500"
			/>
		</div>

		<!-- Tool list -->
		<div class="flex-1 overflow-y-auto">
			{#if loading}
				<div class="flex items-center justify-center py-12 text-sm text-zinc-600">
					<span class="animate-pulse">Loading skills…</span>
				</div>
			{:else if error}
				<div class="p-4 text-sm text-red-400">{error}</div>
			{:else if filtered.length === 0}
				<div class="p-4 text-sm text-zinc-600">No skills match "{search}"</div>
			{:else}
				{#each grouped() as [category, categoryTools]}
					<div>
						<div class="sticky top-0 bg-zinc-950 px-4 py-2 text-[10px] font-semibold uppercase tracking-wider text-zinc-600">
							{category}
						</div>
						{#each categoryTools as tool}
							<button
								class="w-full border-b border-zinc-900 px-4 py-2.5 text-left transition-colors
									hover:bg-zinc-800/50
									{selectedTool?.name === tool.name ? 'bg-zinc-800 text-zinc-100' : 'text-zinc-400'}"
								onclick={() => selectTool(tool)}
							>
								<div class="text-sm font-mono leading-snug">{tool.name}</div>
								{#if tool.description}
									<div class="mt-0.5 text-xs text-zinc-600 leading-snug line-clamp-1">
										{tool.description}
									</div>
								{/if}
							</button>
						{/each}
					</div>
				{/each}
			{/if}
		</div>

		<!-- Count -->
		{#if !loading && !error}
			<div class="border-t border-zinc-800 px-4 py-2 text-[10px] text-zinc-600">
				{filtered.length} of {tools.length} skills
			</div>
		{/if}
	</div>

	<!-- Right: Invocation panel -->
	<div class="flex flex-1 min-h-0 flex-col overflow-y-auto">
		{#if !selectedTool}
			<div class="flex flex-1 items-center justify-center py-20 text-center">
				<div>
					<div class="mb-3 text-4xl opacity-20">⋯</div>
					<p class="text-sm text-zinc-600">Select a skill to invoke</p>
					<p class="mt-1 text-xs text-zinc-700">All {tools.length} skills are listed alphabetically</p>
				</div>
			</div>
		{:else}
			<div class="p-4 md:p-6 space-y-4">
				<!-- Tool header -->
				<div>
					<h2 class="font-mono text-lg font-semibold text-zinc-100">{selectedTool.name}</h2>
					{#if selectedTool.description}
						<p class="mt-1 text-sm text-zinc-400 leading-relaxed">{selectedTool.description}</p>
					{/if}
				</div>

				<!-- Arguments form -->
				{#if properties.length > 0}
					<div class="space-y-3">
						<h3 class="text-xs font-semibold uppercase tracking-wider text-zinc-600">Arguments</h3>
						{#each properties as [name, schema]}
							{@const required = requiredArgs.includes(name)}
							<div>
								<label class="mb-1 block text-xs text-zinc-400" for="arg-{name}">
									<code class="text-zinc-300">{name}</code>
									<span class="ml-1 text-[10px] text-zinc-600">{schema.type}</span>
									{#if required}
										<span class="ml-1 text-red-500">*</span>
									{/if}
								</label>
								{#if schema.description}
									<p class="mb-1 text-[11px] text-zinc-600">{schema.description}</p>
								{/if}
								<input
									id="arg-{name}"
									type="text"
									placeholder={required ? 'required' : 'optional'}
									bind:value={argValues[name]}
									class="w-full rounded-lg border border-zinc-700 bg-zinc-900 px-3 py-2 font-mono text-sm
										text-zinc-100 placeholder:text-zinc-700 focus:border-zinc-500 focus:outline-none
										focus:ring-1 focus:ring-zinc-500"
								/>
							</div>
						{/each}
					</div>
				{:else}
					<p class="text-sm text-zinc-600 italic">No arguments required</p>
				{/if}

				<!-- Invoke button -->
				<button
					class="w-full rounded-lg bg-zinc-100 py-2.5 text-sm font-semibold text-zinc-900
						hover:bg-zinc-200 active:bg-zinc-300 transition-colors disabled:opacity-50"
					disabled={invokingTool !== null}
					onclick={invoke}
				>
					{#if invokingTool}
						<span class="inline-flex items-center gap-2">
							<span class="h-3 w-3 animate-spin rounded-full border-2 border-zinc-900 border-t-transparent"></span>
							Running…
						</span>
					{:else}
						▶ Run {selectedTool.name}
					{/if}
				</button>

				<!-- Result -->
				{#if invokeResult !== null}
					<div>
						<div class="mb-1 text-[10px] uppercase tracking-wider text-emerald-600">Result</div>
						<div class="overflow-auto rounded-lg bg-zinc-950 p-3">
							<pre class="text-xs text-emerald-400">{invokeResult}</pre>
						</div>
					</div>
				{/if}

				{#if invokeError}
					<div>
						<div class="mb-1 text-[10px] uppercase tracking-wider text-red-600">Error</div>
						<div class="overflow-auto rounded-lg border border-red-900/40 bg-red-950/20 p-3">
							<pre class="text-xs text-red-400">{invokeError}</pre>
						</div>
					</div>
				{/if}
			</div>
		{/if}
	</div>
</div>
