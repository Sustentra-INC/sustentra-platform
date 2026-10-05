"""Database housekeeping called from the auth flow.

DB-002: expired sessions and auth tokens are purged opportunistically - call
`purge_expired_auth_rows` after every successful login (no scheduled job).
"""

from __future__ import annotations

from typing import Protocol


class _Executor(Protocol):
    async def fetchval(self, query: str, *args: object) -> object: ...


async def purge_expired_auth_rows(conn: _Executor) -> int:
    """Delete sessions/auth_tokens that expired more than a day ago; return how many.

    Works with an asyncpg connection (or anything with an async `fetchval`). The SQL
    function is SECURITY DEFINER, so it purges across tenants even under RLS.
    """
    removed = await conn.fetchval("SELECT purge_expired_auth_rows()")
    return removed if isinstance(removed, int) else 0
