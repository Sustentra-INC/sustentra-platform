from backend.migrations.db_url import to_async_url


def test_converts_scheme_and_sslmode() -> None:
    assert (
        to_async_url("postgresql://u:p@db.example:5432/app?sslmode=require")
        == "postgresql+asyncpg://u:p@db.example:5432/app?ssl=require"
    )


def test_keeps_other_params_and_async_urls() -> None:
    assert to_async_url("postgres://u@h/db?application_name=x") == "postgresql+asyncpg://u@h/db?application_name=x"
    assert to_async_url("postgresql+asyncpg://u@h/db") == "postgresql+asyncpg://u@h/db"
