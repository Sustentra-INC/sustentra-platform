class ImageParser:
    """Placeholder adapter for image OCR pre-processing."""

    def parse(self, storage_uri: str) -> dict:
        return {"storage_uri": storage_uri, "parser": "image", "status": "not_implemented"}
