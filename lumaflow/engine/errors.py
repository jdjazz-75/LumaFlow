# LumaFlow v1.0 (2026-08-07)
# Categories d'erreurs et exceptions du moteur (ImageIOError, StepError).
from __future__ import annotations

import enum


class ErrorCategory(enum.Enum):
    MISSING_FILE = "missing_file"
    PERMISSION_DENIED = "permission_denied"
    UNSUPPORTED_FORMAT = "unsupported_format"
    CORRUPTED_FILE = "corrupted_file"
    RAW_NOT_DECODABLE = "raw_not_decodable"
    INVALID_PATH = "invalid_path"
    DISK_FULL = "disk_full"
    UNKNOWN = "unknown"


class ImageIOError(Exception):
    def __init__(self, category: ErrorCategory, operation: str, detail: str = "") -> None:
        super().__init__(detail or f"{operation} failed: {category.value}")
        self.category = category
        self.operation = operation
        self.detail = detail


class StepError(Exception):
    def __init__(
        self,
        step_identifier: str,
        step_index: int,
        detail: str,
        cause: BaseException | None = None,
    ) -> None:
        super().__init__(detail)
        self.step_identifier = step_identifier
        self.step_index = step_index
        self.detail = detail
        self.cause = cause
