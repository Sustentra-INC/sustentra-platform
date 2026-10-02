"""Convert libpq-style Postgres URLs to the SQLAlchemy + asyncpg form."""

from __future__ import annotations

from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


def to_async_url(url: str) -> str:
    """postgresql://u:p@h/db?sslmode=require -> postgresql+asyncpg://u:p@h/db?ssl=require

    asyncpg does not understand libpq's `sslmode`; it takes `ssl` with the same values.
    """
    parts = urlsplit(url)
    scheme = parts.scheme
    if scheme in ("postgres", "postgresql", "postgresql+psycopg2"):
        scheme = "postgresql+asyncpg"
    query = []
    for key, value in parse_qsl(parts.query, keep_blank_values=True):
        query.append(("ssl", value) if key == "sslmode" else (key, value))
    return urlunsplit((scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))
