import adapter from '@sveltejs/adapter-cloudflare';
import { vitePreprocess } from '@sveltejs/vite-plugin-svelte';

const cloudflareAdapter = adapter({
	routes: {
		include: ['/*'],
		exclude: ['<all>'],
	},
});

const disableEmulate = process.env.SVELTEKIT_DISABLE_EMULATE === '1';
// Miniflare emulation opens a loopback listener during prerender; disable for locked build environments.
const selectedAdapter = disableEmulate
	? { ...cloudflareAdapter, emulate: undefined }
	: cloudflareAdapter;

/** @type {import('@sveltejs/kit').Config} */
const config = {
	preprocess: vitePreprocess(),
	kit: {
		adapter: selectedAdapter,
		alias: {
			$lib: './src/lib',
			$components: './src/lib/components',
			$stores: './src/lib/stores',
		},
	},
};

export default config;
