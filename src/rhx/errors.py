from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class ErrorCode(str, Enum):
    VALIDATION_ERROR = "VALIDATION_ERROR"
    AUTH_REQUIRED = "AUTH_REQUIRED"
    MFA_REQUIRED = "MFA_REQUIRED"
    RATE_LIMITED = "RATE_LIMITED"
    BROKER_REJECTED = "BROKER_REJECTED"
    LIVE_MODE_OFF = "LIVE_MODE_OFF"
    SAFETY_POLICY_BLOCK = "SAFETY_POLICY_BLOCK"
    INTERNAL_ERROR = "INTERNAL_ERROR"


EXIT_CODE_MAP: dict[ErrorCode, int] = {
    ErrorCode.VALIDATION_ERROR: 2,
    ErrorCode.AUTH_REQUIRED: 3,
    ErrorCode.MFA_REQUIRED: 3,
    ErrorCode.RATE_LIMITED: 4,
    ErrorCode.BROKER_REJECTED: 5,
    ErrorCode.LIVE_MODE_OFF: 6,
    ErrorCode.SAFETY_POLICY_BLOCK: 6,
    ErrorCode.INTERNAL_ERROR: 10,
}


@dataclass
class CLIError(Exception):
    code: ErrorCode
    message: str
    retriable: bool = False

    @property
    def exit_code(self) -> int:
        return EXIT_CODE_MAP.get(self.code, 10)

    def __str__(self) -> str:
        return f"{self.code.value}: {self.message}"
