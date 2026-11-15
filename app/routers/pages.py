from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, PlainTextResponse, RedirectResponse

from app.auth import current_student
from app.templating import path_for, render

router = APIRouter()


@router.get("/", name="home")
async def home(request: Request):
    target = "exam" if current_student(request) else "login"
    return RedirectResponse(path_for(request, target), status_code=303)


@router.get("/healthz", name="healthz", include_in_schema=False)
async def healthz():
    """Liveness probe for containers; does not contact the school system."""
    return PlainTextResponse("ok", headers={"Cache-Control": "no-store"})


@router.get("/about", name="about")
async def about(request: Request):
    return render(request, "pages/about.html", {"active": "about"})


@router.get("/installation", name="installation")
async def installation(request: Request):
    return render(request, "pages/installation.html", {"active": "installation"})


@router.get("/manifest.webmanifest", name="manifest")
async def manifest(request: Request):
    def icon(file: str, size: str) -> dict:
        return {"src": path_for(request, "static", path=f"icons/{file}"), "sizes": size, "type": "image/png"}

    return JSONResponse({
        "name": "TNFSH Scoreboard",
        "short_name": "一中成績查詢",
        "description": "一個簡單的成績查詢系統，讓你不用多次點擊與縮放頁面才能知道成績",
        "lang": "zh-Hant-TW",
        "start_url": path_for(request, "home"),
        "scope": path_for(request, "home"),
        "display": "standalone",
        "orientation": "portrait",
        "background_color": "#212529",
        "theme_color": "#212529",
        "icons": [
            icon("android-chrome-192x192.png", "192x192"),
            icon("android-chrome-512x512.png", "512x512"),
            icon("apple-touch-icon.png", "180x180"),
            icon("mstile-270x270.png", "270x270"),
        ],
        "screenshots": [{
            "src": path_for(request, "static", path="pictures/screenshot1.png"),
            "sizes": "1080x2300",
            "type": "image/png",
            "form_factor": "narrow",
            "label": "段考成績",
        }],
    }, media_type="application/manifest+json")


# 舊版網址
_LEGACY = {
    "/info": "home",
    "/subjectabsence": "subject_absence",
    "/tabledownload": "documents",
    "/resetpw": "change_password",
    "/forgetpw": "forgot_password",
}


def _legacy_redirect(target: str):
    async def endpoint(request: Request):
        return RedirectResponse(path_for(request, target), status_code=301)
    return endpoint


for _path, _target in _LEGACY.items():
    router.add_api_route(_path, _legacy_redirect(_target), methods=["GET"], include_in_schema=False)
