"""SQLite persistence layer.

Public API: MaterializedContent, Subscription, SubscriptionKind,
    SubscriptionRegistry, cleanup_stale_checkpoints, clear_checkpoint,
    content_hash, init_history_store, load_checkpoint,
    resolve_history_db_path, save_checkpoint
Internal: history, subscriptions
"""

from autopoiesis.store.history import (
    cleanup_stale_checkpoints,
    clear_checkpoint,
    init_history_store,
    load_checkpoint,
    resolve_history_db_path,
    save_checkpoint,
)
from autopoiesis.store.knowledge import (
    FileMeta,
    SearchResult,
    build_backlink_index,
    ensure_journal_entry,
    format_search_results,
    init_knowledge_index,
    known_types,
    load_knowledge_context,
    parse_frontmatter,
    register_types,
    reindex_knowledge,
    search_knowledge,
    strip_frontmatter,
)
from autopoiesis.store.subscriptions import (
    MaterializedContent,
    Subscription,
    SubscriptionKind,
    SubscriptionRegistry,
    content_hash,
)

__all__ = [
    "FileMeta",
    "MaterializedContent",
    "SearchResult",
    "Subscription",
    "SubscriptionKind",
    "SubscriptionRegistry",
    "build_backlink_index",
    "cleanup_stale_checkpoints",
    "clear_checkpoint",
    "content_hash",
    "ensure_journal_entry",
    "format_search_results",
    "init_history_store",
    "init_knowledge_index",
    "known_types",
    "load_checkpoint",
    "load_knowledge_context",
    "parse_frontmatter",
    "register_types",
    "reindex_knowledge",
    "resolve_history_db_path",
    "save_checkpoint",
    "search_knowledge",
    "strip_frontmatter",
]
