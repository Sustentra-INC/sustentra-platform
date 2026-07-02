from backend.app.main import app


def test_app_is_constructible() -> None:
    assert app is not None
    assert app.title == "Sustentra Evidence Extraction API"
