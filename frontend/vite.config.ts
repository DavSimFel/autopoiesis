import { sveltekit } from '@sveltejs/kit/vite';
import { defineConfig } from 'vite';
import tailwindcss from '@tailwindcss/vite';
import { VitePWA } from 'vite-plugin-pwa';

export default defineConfig({
	plugins: [
		tailwindcss(),
		sveltekit(),
		VitePWA({
			registerType: 'autoUpdate',
			strategies: 'generateSW',
			manifest: {
				name: 'Autopoiesis',
				short_name: 'Autopoiesis',
				description: 'AI Agent Shell — Autopoiesis Control Panel',
				theme_color: '#09090b',
				background_color: '#09090b',
				display: 'standalone',
				orientation: 'portrait-primary',
				scope: '/',
				start_url: '/',
				icons: [
					{
						src: '/icons/icon-192.png',
						sizes: '192x192',
						type: 'image/png',
					},
					{
						src: '/icons/icon-512.png',
						sizes: '512x512',
						type: 'image/png',
					},
					{
						src: '/icons/icon-512.png',
						sizes: '512x512',
						type: 'image/png',
						purpose: 'maskable',
					},
				],
			},
			workbox: {
				// Cache shell assets; never cache MCP/SSE — they must hit the network
				globPatterns: ['**/*.{js,css,html,ico,png,svg,woff2}'],
				navigateFallback: '/',
				navigateFallbackDenylist: [/^\/mcp/],
				runtimeCaching: [
					{
						// MCP tool calls — network-only
						urlPattern: /\/mcp\//i,
						handler: 'NetworkOnly',
					},
				],
			},
			devOptions: {
				enabled: false,
			},
		}),
	],
});
