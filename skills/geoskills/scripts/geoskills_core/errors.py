"""Expected, machine-readable errors used by the GeoSkills core."""

from __future__ import annotations

from typing import Any, Mapping


class GeoSkillsError(Exception):
    """Base class for an expected error that can be shown to a user."""

    default_code = "E000"

    def __init__(
        self,
        message: str,
        *,
        code: str | None = None,
        details: Mapping[str, Any] | None = None,
        suggested_action: str | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code or self.default_code
        self.details = dict(details or {})
        self.suggested_action = suggested_action

    def to_issue(self) -> dict[str, Any]:
        """Return a JSON-serializable error issue."""
        result: dict[str, Any] = {
            "code": self.code,
            "severity": "error",
            "message": str(self),
        }
        if self.details:
            result["details"] = self.details
        if self.suggested_action:
            result["suggested_action"] = self.suggested_action
        return result


class InputValidationError(GeoSkillsError):
    """The input path or table does not meet the public data contract."""

    default_code = "E100"


class UnsupportedFormatError(InputValidationError):
    """The input file extension is not supported."""

    default_code = "E101"


class FileSizeError(InputValidationError):
    """The input file exceeds the configured safety limit."""

    default_code = "E102"


class TextEncodingError(InputValidationError):
    """The text file is neither valid UTF-8 nor valid GB18030."""

    default_code = "E103"


class WorksheetError(InputValidationError):
    """A requested Excel worksheet does not exist."""

    default_code = "E104"


class TableReadError(InputValidationError):
    """A supported file could not be parsed as a table."""

    default_code = "E105"


class PlottingError(GeoSkillsError):
    """An expected problem that makes figure creation or export unsafe."""

    default_code = "E500"
