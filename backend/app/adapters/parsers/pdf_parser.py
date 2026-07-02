class PdfParser:
    """Placeholder adapter for PDF parsing fallback."""

    def parse(self, storage_uri: str) -> dict:
        return {"storage_uri": storage_uri, "parser": "pdf", "status": "not_implemented"}
