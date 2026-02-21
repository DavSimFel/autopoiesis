import { clsx, type ClassValue } from 'clsx';
import { twMerge } from 'tailwind-merge';

export function cn(...inputs: ClassValue[]) {
	return twMerge(clsx(inputs));
}

export function formatRelativeTime(ts: string): string {
	const delta = Date.now() - new Date(ts).getTime();
	if (delta < 60_000) return 'just now';
	if (delta < 3_600_000) return `${Math.floor(delta / 60_000)}m ago`;
	if (delta < 86_400_000) return `${Math.floor(delta / 3_600_000)}h ago`;
	return new Date(ts).toLocaleDateString();
}

export function formatDuration(ms: number): string {
	if (ms < 1_000) return `${ms}ms`;
	if (ms < 60_000) return `${(ms / 1_000).toFixed(1)}s`;
	return `${Math.floor(ms / 60_000)}m ${Math.floor((ms % 60_000) / 1_000)}s`;
}

export function riskColor(risk: 'low' | 'medium' | 'high' | 'critical'): string {
	return {
		low: 'text-emerald-400',
		medium: 'text-amber-400',
		high: 'text-orange-400',
		critical: 'text-red-400',
	}[risk];
}

export function riskBg(risk: 'low' | 'medium' | 'high' | 'critical'): string {
	return {
		low: 'bg-emerald-900/20 border-emerald-800/40',
		medium: 'bg-amber-900/20 border-amber-800/40',
		high: 'bg-orange-900/20 border-orange-800/40',
		critical: 'bg-red-900/20 border-red-800/40',
	}[risk];
}

export function statusColor(status: 'healthy' | 'degraded' | 'offline' | 'busy'): string {
	return {
		healthy: 'bg-emerald-500',
		busy: 'bg-amber-500',
		degraded: 'bg-orange-500',
		offline: 'bg-zinc-500',
	}[status];
}
