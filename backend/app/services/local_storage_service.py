from __future__ import annotations

import re
from pathlib import Path

_SAFE_COMPONENT_RE = re.compile(r"[^A-Za-z0-9._-]+")
_SAFE_FILENAME_RE = re.compile(r"[^A-Za-z0-9._-]+")


class LocalStorageService:
    """Stores uploaded files under local runtime storage (PR10)."""

    def __init__(self, storage_root: str | Path = "local-data/uploads"):
        root_input = Path(storage_root)
        self._storage_root = root_input.resolve()
        if root_input.is_absolute():
            self._storage_uri_prefix = Path(root_input.name)
        else:
            self._storage_uri_prefix = root_input

    @property
    def storage_root(self) -> Path:
        return self._storage_root

    @property
    def storage_uri_prefix(self) -> Path:
        return self._storage_uri_prefix

    def save_upload(
        self,
        *,
        file_name: str,
        content: bytes,
        engagement_id: str,
        evidence_id: str,
        document_id: str,
    ) -> dict:
        if not isinstance(content, (bytes, bytearray)):
            raise ValueError("content must be bytes.")
        raw_bytes = bytes(content)
        if not raw_bytes:
            raise ValueError("Upload content cannot be empty.")

        safe_file_name = self._sanitize_file_name(file_name)
        safe_engagement_id = self._sanitize_component(engagement_id, "engagement_id")
        safe_evidence_id = self._sanitize_component(evidence_id, "evidence_id")
        safe_document_id = self._sanitize_component(document_id, "document_id")

        relative_suffix = (
            Path(safe_engagement_id)
            / safe_evidence_id
            / safe_document_id
            / safe_file_name
        )

        target_path = self._safe_target_path(relative_suffix)
        final_file_name = safe_file_name

        if target_path.exists():
            stem = Path(safe_file_name).stem
            suffix = Path(safe_file_name).suffix
            counter = 1
            while target_path.exists():
                final_file_name = f"{stem}_{counter}{suffix}"
                relative_suffix = (
                    Path(safe_engagement_id)
                    / safe_evidence_id
                    / safe_document_id
                    / final_file_name
                )
                target_path = self._safe_target_path(relative_suffix)
                counter += 1

        target_path.parent.mkdir(parents=True, exist_ok=True)
        target_path.write_bytes(raw_bytes)

        storage_uri = (self._storage_uri_prefix / relative_suffix).as_posix()
        return {
            "storage_uri": storage_uri,
            "stored_file_name": final_file_name,
            "size_bytes": len(raw_bytes),
        }

    def resolve_storage_uri(self, storage_uri: str) -> Path:
        if not isinstance(storage_uri, str) or not storage_uri.strip():
            raise ValueError("storage_uri must be a non-empty string.")

        uri_path = Path(storage_uri)
        if uri_path.is_absolute():
            raise ValueError("storage_uri must be a relative path.")

        uri_parts = uri_path.parts
        prefix_parts = self._storage_uri_prefix.parts
        if len(uri_parts) >= len(prefix_parts) and tuple(uri_parts[: len(prefix_parts)]) == prefix_parts:
            suffix_parts = uri_parts[len(prefix_parts) :]
        else:
            suffix_parts = uri_parts

        candidate = self._storage_root.joinpath(*suffix_parts).resolve()
        if not self._is_within_root(candidate):
            raise ValueError("storage_uri resolves outside of storage root.")
        return candidate

    def exists(self, storage_uri: str) -> bool:
        try:
            path = self.resolve_storage_uri(storage_uri)
        except ValueError:
            return False
        return path.exists() and path.is_file()

    def _safe_target_path(self, relative_suffix: Path) -> Path:
        target = self._storage_root.joinpath(relative_suffix).resolve()
        if not self._is_within_root(target):
            raise ValueError("Resolved upload path escapes storage root.")
        return target

    def _is_within_root(self, path: Path) -> bool:
        try:
            path.relative_to(self._storage_root)
            return True
        except ValueError:
            return False

    @staticmethod
    def _sanitize_component(value: str, field_name: str) -> str:
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{field_name} is required.")
        sanitized = _SAFE_COMPONENT_RE.sub("_", value.strip())
        sanitized = sanitized.strip("._")
        if not sanitized:
            raise ValueError(f"{field_name} contains no safe characters.")
        return sanitized

    @staticmethod
    def _sanitize_file_name(file_name: str) -> str:
        if not isinstance(file_name, str) or not file_name.strip():
            raise ValueError("file_name is required.")

        basename = file_name.strip().replace("\\", "/").split("/")[-1]
        basename = _SAFE_FILENAME_RE.sub("_", basename)
        basename = basename.strip(" ")
        if not basename or basename in {".", ".."}:
            raise ValueError("file_name is invalid after sanitization.")
        return basename
