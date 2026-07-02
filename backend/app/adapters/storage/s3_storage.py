class S3Storage:
    """Placeholder adapter for S3 document storage interactions."""

    def put_object(self, key: str, content: bytes) -> str:
        return f"s3://replace-me/{key}"

    def get_object(self, key: str) -> bytes:
        return b""
