"""SQLite persistence layer.

Public API: MaterializedContent, Subscription, SubscriptionKind,
    SubscriptionRegistry, cleanup_stale_checkpoints, clear_checkpoint,
    content_hash, init_history_store, load_checkpoint,
    resolve_history_db_path, save_checkpoint
Internal: history, subscriptions
"""

from store.history import (
    cleanup_stale_checkpoints,
    clear_checkpoint,
    init_history_store,
    load_checkpoint,
    resolve_history_db_path,
    save_checkpoint,
)
from store.knowledge import (
    SearchResult,
    ensure_journal_entry,
    format_search_results,
    init_knowledge_index,
    load_knowledge_context,
    reindex_knowledge,
    search_knowledge,
)
from store.subscriptions import (
    MaterializedContent,
    Subscription,
    SubscriptionKind,
    SubscriptionRegistry,
    content_hash,
)

__all__ = [
    "MaterializedContent",
    "SearchResult",
    "Subscription",
    "SubscriptionKind",
    "SubscriptionRegistry",
    "cleanup_stale_checkpoints",
    "clear_checkpoint",
    "content_hash",
    "ensure_journal_entry",
    "format_search_results",
    "init_history_store",
    "init_knowledge_index",
    "load_checkpoint",
    "load_knowledge_context",
    "reindex_knowledge",
    "resolve_history_db_path",
    "save_checkpoint",
    "search_knowledge",
]
