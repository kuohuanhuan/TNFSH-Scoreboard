import re
from datetime import date
from typing import Annotated

from fastapi import APIRouter, Form, Request
from fastapi.responses import RedirectResponse, Response

from app.auth import SchoolDep, StudentDep, Student, current_student, login_user, logout_user
from app.errors import ErrorCode, SchoolError
from app.school import ocr
from app.school.client import SchoolClient
from app.templating import path_for, render, templates

router = APIRouter()


def _safe_next(request: Request, value: str | None) -> str:
    """Only allow redirects to local paths."""
    if value and value.startswith("/") and not value.startswith("//") and "\\" not in value:
        return value
    return path_for(request, "exam")


def _is_htmx(request: Request) -> bool:
    return request.headers.get("HX-Request") == "true"


def _redirect(request: Request, url: str) -> Response:
    """Full page redirect so that the navigation reflects the new login state."""
    if _is_htmx(request):
        return Response(status_code=204, headers={"HX-Redirect": url})
    return RedirectResponse(url, status_code=303)


# ---------------------------------------------------------------------- login


async def _captcha_context(school: SchoolClient) -> dict:
    try:
        return {"captcha": await school.get_captcha(), "captcha_error": None}
    except SchoolError as exc:
        return {"captcha": None, "captcha_error": exc.message}


def _login_form(request: Request, *, partial: bool, status_code: int = 200, **ctx) -> Response:
    ctx.setdefault("ocr_available", ocr.available())
    ctx.setdefault("manual", not ctx["ocr_available"])
    ctx.setdefault("username", "")
    ctx.setdefault("error", None)
    if partial:
        return templates.TemplateResponse(request, "partials/login_form.html", ctx, status_code=status_code)
    return render(request, "pages/login.html", {"active": "login", **ctx}, status_code=status_code)


@router.get("/login", name="login")
async def login_page(request: Request, school: SchoolClient = SchoolDep, next: str | None = None):
    if current_student(request):
        return RedirectResponse(_safe_next(request, next), status_code=303)
    ctx: dict = {"next": next}
    if not ocr.available():
        ctx.update(await _captcha_context(school))
    return _login_form(request, partial=False, **ctx)


@router.get("/login/captcha", name="login_captcha")
async def login_captcha(request: Request, school: SchoolClient = SchoolDep):
    return templates.TemplateResponse(request, "partials/captcha.html", await _captcha_context(school))


@router.post("/login", name="login_submit")
async def login_submit(
    request: Request,
    username: Annotated[str, Form()],
    password: Annotated[str, Form()],
    school: SchoolClient = SchoolDep,
    captcha: Annotated[str, Form()] = "",
    captcha_src: Annotated[str, Form()] = "",
    next: Annotated[str | None, Form()] = None,
):
    manual = bool(captcha) or not ocr.available()
    partial = _is_htmx(request)

    async def fail(message: str, *, force_manual: bool = False) -> Response:
        is_manual = manual or force_manual
        ctx = {"error": message, "username": username, "next": next, "manual": is_manual}
        if is_manual:
            ctx.update(await _captcha_context(school))
        return _login_form(request, partial=partial, status_code=200 if partial else 400, **ctx)

    username = username.strip()
    if not username or not password:
        return await fail("請輸入帳號與密碼")

    try:
        if manual:
            code = captcha.strip()
        else:
            code = await ocr.solve(await school.get_captcha()) or ""
        if len(code) != 4:
            return await fail(
                "驗證碼錯誤" if manual else "自動辨識驗證碼失敗，請手動輸入",
                force_manual=not manual,
            )

        session_key, password_expired = await school.login(username, password, code, captcha_src)
        info = await school.get_student_info(session_key)
    except SchoolError as exc:
        if exc.code == ErrorCode.WRONG_CAPTCHA and not manual:
            return await fail("自動辨識驗證碼失敗，請手動輸入", force_manual=True)
        return await fail(exc.message)

    login_user(request, session_key, info)
    if password_expired:
        target = path_for(request, "change_password", _query={"expired": 1, "next": next})
    else:
        target = _safe_next(request, next)
    return _redirect(request, target)


@router.post("/logout", name="logout")
async def logout(request: Request):
    logout_user(request)
    return _redirect(request, path_for(request, "login"))


# ---------------------------------------------------------------------- change password

_SPECIAL_CHARS = re.compile(r"""[~`!@#$%^&*()_+=\-\[\]\\';,./{}|":<>?]""")


def validate_new_password(current: str, new: str, confirm: str) -> str | None:
    if current == new:
        return "新密碼不可與原本的密碼相同"
    if new != confirm:
        return "新密碼與確認密碼不同"
    if not 8 <= len(new) <= 30:
        return "密碼長度需介於 8 到 30 個字元之間"
    if not (re.search(r"\d", new) and re.search(r"[a-z]", new, re.I) and _SPECIAL_CHARS.search(new)):
        return "密碼必須同時含有數字、英文字母與特殊符號"
    return None


@router.get("/change-password", name="change_password")
async def change_password_page(request: Request, student: Student = StudentDep,
                               expired: bool = False, next: str | None = None):
    return render(request, "pages/change_password.html", {
        "active": "change_password", "expired": expired, "next": _safe_next(request, next),
        "error": None, "success": False,
    })


@router.post("/change-password", name="change_password_submit")
async def change_password_submit(
    request: Request,
    current_password: Annotated[str, Form()],
    new_password: Annotated[str, Form()],
    confirm_password: Annotated[str, Form()],
    student: Student = StudentDep,
    school: SchoolClient = SchoolDep,
):
    error = validate_new_password(current_password, new_password, confirm_password)
    if error is None:
        try:
            error = await school.update_password(student.session_key, current_password, new_password, confirm_password)
        except SchoolError as exc:
            error = exc.message

    ctx = {"error": error, "success": error is None}
    if error is None:
        # 校務系統會讓舊的 session 失效
        logout_user(request)
    if _is_htmx(request):
        return templates.TemplateResponse(request, "partials/change_password_form.html", ctx)
    return render(request, "pages/change_password.html", {"active": "change_password", **ctx},
                  status_code=200 if error is None else 400)


# ---------------------------------------------------------------------- forgot password

_ID_LETTERS = "ABCDEFGHJKLMNPQRSTUVXYWZIO"  # A=10 … O=35


def valid_national_id(value: str) -> bool:
    """Taiwan national ID checksum."""
    value = value.upper()
    if not re.fullmatch(r"[A-Z][12]\d{8}", value):
        return False
    letter = _ID_LETTERS.index(value[0]) + 10
    digits = [letter // 10, letter % 10, *map(int, value[1:])]
    weights = [1, 9, 8, 7, 6, 5, 4, 3, 2, 1, 1]
    return sum(d * w for d, w in zip(digits, weights)) % 10 == 0


@router.get("/forgot-password", name="forgot_password")
async def forgot_password_page(request: Request):
    return render(request, "pages/forgot_password.html", {"active": "login", "error": None, "success": False})


@router.post("/forgot-password", name="forgot_password_submit")
async def forgot_password_submit(
    request: Request,
    account: Annotated[str, Form()],
    name: Annotated[str, Form()],
    id_number: Annotated[str, Form()],
    birthday: Annotated[date, Form()],
    school: SchoolClient = SchoolDep,
):
    error = None
    if not valid_national_id(id_number.strip()):
        error = "身分證字號格式錯誤"
    elif not date(1950, 1, 1) <= birthday <= date.today():
        error = "生日日期錯誤"
    else:
        try:
            await school.forget_password(account.strip(), name.strip(), id_number.strip().upper(),
                                         birthday.strftime("%Y%m%d"))
        except SchoolError as exc:
            error = exc.message

    ctx = {"error": error, "success": error is None}
    if _is_htmx(request):
        return templates.TemplateResponse(request, "partials/forgot_password_form.html", ctx)
    return render(request, "pages/forgot_password.html", {"active": "login", **ctx},
                  status_code=200 if error is None else 400)
