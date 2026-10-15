"""External data-source providers.

Providers only talk to third-party tools over their public interfaces. They do
not parse chat payloads themselves; conversion to :class:`ChatMessage` stays in
the matching adapter module.
"""

from __future__ import annotations

from .wechat_database_provider import (
    DatabaseUnreadable,
    QueryFailed,
    WeChatDatabaseError,
    WeChatDatabaseProvider,
    WeChatSession,
    WcdbHelperNotFound,
    WcdbLibraryNotFound,
    message_table_name,
)

__all__ = [
    "DatabaseUnreadable",
    "QueryFailed",
    "WcdbHelperNotFound",
    "WcdbLibraryNotFound",
    "WeChatDatabaseError",
    "WeChatDatabaseProvider",
    "WeChatSession",
    "message_table_name",
]
