class TextractParser:
    """Placeholder adapter for AWS Textract extraction output."""

    def parse(self, storage_uri: str) -> dict:
        return {"storage_uri": storage_uri, "parser": "textract", "status": "not_implemented"}
