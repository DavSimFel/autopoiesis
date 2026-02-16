"""SQLite persistence layer.

Public API: MaterializedContent, Subscription, SubscriptionKind,
    SubscriptionRegistry, cleanup_stale_checkpoints, clear_checkpoint,
    combined_search, content_hash, get_memory_file_snippet,
    init_history_store, init_memory_store, load_checkpoint,
    resolve_history_db_path, resolve_memory_db_path, save_checkpoint,
    save_memory, search_memory
Internal: history, memory, subscriptions
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
    migrate_memory_to_knowledge,
    reindex_knowledge,
    search_knowledge,
)
from store.memory import (
    combined_search,
    get_memory_file_snippet,
    init_memory_store,
    resolve_memory_db_path,
    save_memory,
    search_memory,
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
    "combined_search",
    "content_hash",
    "ensure_journal_entry",
    "format_search_results",
    "get_memory_file_snippet",
    "init_history_store",
    "init_knowledge_index",
    "init_memory_store",
    "load_checkpoint",
    "load_knowledge_context",
    "migrate_memory_to_knowledge",
    "reindex_knowledge",
    "resolve_history_db_path",
    "resolve_memory_db_path",
    "save_checkpoint",
    "save_memory",
    "search_knowledge",
    "search_memory",
]
