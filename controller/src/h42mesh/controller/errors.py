"""API errors: a stable English code (translated by the GUI) and a message."""

from typing import Any

from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse

from h42mesh.controller.schemas.errors import ErrorResponse


class ApiError(Exception):
    def __init__(
        self,
        status_code: int,
        code: str,
        message: str,
        headers: dict[str, str] | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message
        self.headers = headers


def not_authenticated() -> ApiError:
    return ApiError(status.HTTP_401_UNAUTHORIZED, "not_authenticated", "Authentication required")


async def _handle_api_error(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, ApiError)  # noqa: S101 (registered for ApiError only)
    body = ErrorResponse(code=exc.code, message=exc.message)
    return JSONResponse(body.model_dump(), status_code=exc.status_code, headers=exc.headers)


def install_error_handlers(app: FastAPI) -> None:
    app.add_exception_handler(ApiError, _handle_api_error)


def error_responses(*status_codes: int) -> dict[int | str, dict[str, Any]]:
    """OpenAPI ``responses`` entries documenting ErrorResponse for these statuses."""
    return {code: {"model": ErrorResponse} for code in status_codes}
