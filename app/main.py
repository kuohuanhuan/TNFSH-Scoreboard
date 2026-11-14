import logging
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import urlencode, urlsplit

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.staticfiles import StaticFiles
from starlette.applications import Starlette
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.sessions import SessionMiddleware
from starlette.responses import RedirectResponse, Response
from starlette.routing import Mount, Route

from app.config import Settings, get_settings
from app.errors import ErrorCode, LoginRequired, SchoolError
from app.routers import auth, pages, records, scores
from app.school.client import SchoolClient
from app.templating import is_main_swap, path_for, render, templates

logger = logging.getLogger("scoreboard")

STATIC_DIR = Path(__file__).parent / "static"


def _is_htmx(request: Request) -> bool:
    return request.headers.get("HX-Request") == "true"


def _toast(request: Request, message: str, status_code: int) -> Response:
    """Report an error of a background HTMX request (e.g. a delete button) as a toast."""
    response = templates.TemplateResponse(
        request, "partials/toast.html", {"message": message, "level": "danger"}, status_code=status_code,
    )
    response.headers["HX-Retarget"] = "#toasts"
    response.headers["HX-Reswap"] = "beforeend"
    return response


def _error_page(request: Request, title: str, message: str, status_code: int, **extra) -> Response:
    if _is_htmx(request) and not is_main_swap(request):
        return _toast(request, message, status_code)
    return render(request, "error.html", {"title": title, "message": message, **extra}, status_code=status_code)


async def _login_required(request: Request, _exc: LoginRequired) -> Response:
    if _is_htmx(request) and not is_main_swap(request):
        current = urlsplit(request.headers.get("HX-Current-URL", ""))
        target = current.path + (f"?{current.query}" if current.query else "")
    else:
        target = request.url.path + (f"?{request.url.query}" if request.url.query else "")
    login_url = path_for(request, "login") + "?" + urlencode({"next": target})

    if _is_htmx(request):
        return Response(status_code=204, headers={"HX-Redirect": login_url})
    return RedirectResponse(login_url, status_code=303)


async def _school_error(request: Request, exc: SchoolError) -> Response:
    if exc.code == ErrorCode.REMOTE:
        logger.warning("school system error on %s: %r", request.url.path, exc.__cause__ or exc)
    status = 400 if exc.code == ErrorCode.INVALID_PARAM else 502
    return _error_page(request, "校務系統出現異常", exc.message, status, remote=True)


async def _validation_error(request: Request, exc: RequestValidationError) -> Response:
    return _error_page(request, "參數錯誤", "網址或表單的參數不正確，請回到上一頁重新操作。", 400)


async def _http_error(request: Request, exc: StarletteHTTPException) -> Response:
    if exc.status_code == 404:
        return _error_page(request, "找不到頁面", "這個頁面不存在，可能已經移動或刪除。", 404)
    return _error_page(request, "發生錯誤", str(exc.detail), exc.status_code)


async def _unhandled_error(request: Request, exc: Exception) -> Response:
    logger.exception("unhandled error on %s", request.url.path, exc_info=exc)
    return _error_page(request, "發生錯誤", "伺服器發生未預期的錯誤。", 500, remote=True)


def create_app(settings: Settings | None = None, school: SchoolClient | None = None) -> Starlette:
    settings = settings or get_settings()

    app = FastAPI(
        title="TNFSH Scoreboard",
        debug=settings.debug,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    app.state.settings = settings

    @asynccontextmanager
    async def lifespan(_):
        client = school or SchoolClient(settings)
        await client.start()
        app.state.school = client
        try:
            yield
        finally:
            await client.close()

    app.add_middleware(
        SessionMiddleware,
        secret_key=settings.secret_key,
        session_cookie="scoreboard_session",
        max_age=settings.session_max_age,
        path=settings.base_url,
        same_site="lax",
        https_only=settings.secure_cookies,
    )

    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
    for module in (pages, auth, scores, records):
        app.include_router(module.router)

    app.add_exception_handler(LoginRequired, _login_required)
    app.add_exception_handler(SchoolError, _school_error)
    app.add_exception_handler(RequestValidationError, _validation_error)
    app.add_exception_handler(StarletteHTTPException, _http_error)
    app.add_exception_handler(Exception, _unhandled_error)

    if settings.base_url == "/":
        app.router.lifespan_context = lifespan
        return app

    # 掛載在子路徑下（例如 /scoreboard），外層應用負責 lifespan 與根路徑導向
    base = settings.base_url

    async def to_base(_request) -> Response:
        return RedirectResponse(base + "/")

    return Starlette(
        routes=[Route("/", to_base), Mount(base, app=app)],
        lifespan=lifespan,
    )


app = create_app()
