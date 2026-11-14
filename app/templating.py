from pathlib import Path
from typing import Any
from urllib.parse import urlencode

from fastapi import Request
from fastapi.templating import Jinja2Templates
from jinja2 import pass_context
from starlette.responses import Response

from app import __version__
from app.auth import current_student
from app.school import codes
from app.school.models import PERIOD_NAMES, REWARD_NAMES

templates = Jinja2Templates(directory=Path(__file__).parent / "templates")
env = templates.env
env.trim_blocks = True
env.lstrip_blocks = True


def path_for(request: Request, name: str, /, _query: dict | None = None, **params: Any) -> str:
    """Site-relative URL for a route, honouring the mount path (``BASE_URL``)."""
    path = request.scope.get("root_path", "").rstrip("/") + str(request.app.url_path_for(name, **params))
    if _query:
        query = {k: v for k, v in _query.items() if v is not None}
        if query:
            path += "?" + urlencode(query)
    return path


@pass_context
def _path_for(context: dict, name: str, /, _query: dict | None = None, **params: Any) -> str:
    return path_for(context["request"], name, _query, **params)


@pass_context
def _static(context: dict, path: str) -> str:
    return _path_for(context, "static", path=path) + f"?v={__version__}"


def _or_dash(value: Any, placeholder: str = "尚未公布") -> Any:
    return placeholder if value is None or value == "" else value


def _number(value: Any, digits: int = 2) -> Any:
    try:
        number = round(float(value), digits)
    except (TypeError, ValueError):
        return _or_dash(value)
    return int(number) if number.is_integer() else number


env.globals.update(
    path_for=_path_for,
    static=_static,
    codes=codes,
    PERIOD_NAMES=PERIOD_NAMES,
    REWARD_NAMES=REWARD_NAMES,
    app_version=__version__,
)
env.filters.update(or_dash=_or_dash, number=_number)


def is_main_swap(request: Request) -> bool:
    """True for HTMX navigations that only need the ``<main>`` content."""
    return request.headers.get("HX-Request") == "true" and request.headers.get("HX-Target") == "main"


def render(
    request: Request,
    template: str,
    context: dict[str, Any] | None = None,
    *,
    status_code: int = 200,
    headers: dict[str, str] | None = None,
) -> Response:
    ctx = {
        "student": current_student(request),
        "partial": is_main_swap(request),
        "active": None,
        **(context or {}),
    }
    response = templates.TemplateResponse(request, template, ctx, status_code=status_code, headers=headers)
    # 依 HX-Request 回傳不同內容，避免瀏覽器快取混用完整頁面與片段
    response.headers["Vary"] = "HX-Request, HX-Target"
    response.headers.setdefault("Cache-Control", "no-store")
    return response
