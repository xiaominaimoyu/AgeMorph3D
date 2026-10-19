"""Application failures with stable, public-safe API messages."""

from pydantic import BaseModel


class ErrorResponse(BaseModel):
    detail: str
    code: str


class ApiError(Exception):
    def __init__(self, status_code: int, code: str, detail: str) -> None:
        super().__init__(detail)
        self.status_code = status_code
        self.code = code
        self.detail = detail
