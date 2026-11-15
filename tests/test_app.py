import json
import re

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.errors import ErrorCode, SchoolError
from app.main import create_app
from tests.conftest import HTMX_MAIN

PAGES = ["/exam", "/term", "/graduation", "/reward", "/absence", "/subject-absence", "/leave", "/documents",
         "/change-password"]


def text(html: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html))


# ---------------------------------------------------------------------- auth


@pytest.mark.parametrize("path", PAGES)
def test_pages_require_login(client, path):
    r = client.get(path)
    assert r.status_code == 303
    assert r.headers["location"] == f"/login?next=%2F{path[1:]}"


def test_htmx_login_redirect(client):
    r = client.get("/exam", headers=HTMX_MAIN)
    assert r.status_code == 204
    assert r.headers["HX-Redirect"].startswith("/login?next=")


def test_home_redirects(client, logged_in):
    assert client.get("/").headers["location"] == "/exam"


def test_login_page_and_manual_captcha(client):
    r = client.get("/login")
    assert r.status_code == 200
    assert 'name="captcha"' in r.text  # OCR 無法使用時直接顯示驗證碼欄位
    assert "data:image/png;base64" in r.text


def test_login_success_sets_session(client, school):
    r = client.post("/login", data={"username": "s1", "password": "pw", "captcha": "AbCd", "next": "/term?semester=201"})
    assert r.status_code == 303
    assert r.headers["location"] == "/term?semester=201"
    assert school.calls[0] == ("login", "s1", "pw", "AbCd")
    assert "scoreboard_session" in client.cookies
    assert "3180 7" not in client.get("/exam").text
    assert "31807 王小明" in client.get("/exam").text


def test_login_rejects_open_redirect(client):
    r = client.post("/login", data={"username": "s1", "password": "pw", "captcha": "abcd", "next": "//evil.example"})
    assert r.headers["location"] == "/exam"


def test_login_htmx_error_returns_form_fragment(client, school):
    school.login_error = SchoolError(ErrorCode.WRONG_CREDENTIALS)
    r = client.post("/login", data={"username": "s1", "password": "pw", "captcha": "abcd"},
                    headers={"HX-Request": "true", "HX-Target": "login-form"})
    assert r.status_code == 200
    assert r.text.lstrip().startswith("<form")
    assert "帳號或密碼錯誤" in r.text
    assert 'value="s1"' in r.text
    assert "<html" not in r.text


def test_login_htmx_success_uses_hx_redirect(client):
    r = client.post("/login", data={"username": "s1", "password": "pw", "captcha": "abcd"},
                    headers={"HX-Request": "true"})
    assert r.status_code == 204
    assert r.headers["HX-Redirect"] == "/exam"


def test_login_short_captcha(client, school):
    r = client.post("/login", data={"username": "s1", "password": "pw", "captcha": "ab"})
    assert r.status_code == 400
    assert "驗證碼錯誤" in r.text
    assert not school.calls


def test_password_expired_redirects_to_change_password(client, school):
    school.password_expired = True
    r = client.post("/login", data={"username": "s1", "password": "pw", "captcha": "abcd"})
    assert r.headers["location"].startswith("/change-password?expired=1")
    assert "180 天" in client.get(r.headers["location"]).text


def test_logout(logged_in):
    r = logged_in.post("/logout")
    assert r.headers["location"] == "/login"
    assert logged_in.get("/exam").status_code == 303


def test_change_password_validation_and_success(logged_in, school):
    r = logged_in.post("/change-password", data={"current_password": "a", "new_password": "short", "confirm_password": "short"})
    assert r.status_code == 400 and "8 到 30" in r.text
    r = logged_in.post("/change-password", data={"current_password": "a", "new_password": "Abcdefg1!", "confirm_password": "x"})
    assert "新密碼與確認密碼不同" in r.text
    r = logged_in.post("/change-password", data={"current_password": "a", "new_password": "Abcdefg1!",
                                                 "confirm_password": "Abcdefg1!"}, headers={"HX-Request": "true"})
    assert "密碼已更新" in r.text
    assert school.calls[-1] == ("update_password", "a", "Abcdefg1!")
    assert logged_in.get("/exam").status_code == 303  # 已登出


def test_forgot_password(client, school):
    data = {"account": "s1", "name": "王小明", "id_number": "A123456789", "birthday": "2008-01-02"}
    r = client.post("/forgot-password", data={**data, "id_number": "A123456788"})
    assert "身分證字號格式錯誤" in r.text
    r = client.post("/forgot-password", data=data, headers={"HX-Request": "true"})
    assert "申請已送出" in r.text
    assert school.calls[-1] == ("forget_password", "s1", "王小明", "A123456789", "20080102")


# ---------------------------------------------------------------------- pages


@pytest.mark.parametrize("path", PAGES)
def test_pages_render_full_and_partial(logged_in, path):
    full = logged_in.get(path)
    assert full.status_code == 200, full.text
    assert full.text.startswith("<!doctype html>")
    assert 'id="primary-nav"' in full.text

    partial = logged_in.get(path, headers=HTMX_MAIN)
    assert partial.status_code == 200
    assert partial.text.lstrip().startswith("<title>")
    assert "<html" not in partial.text and 'id="primary-nav"' not in partial.text
    assert partial.headers["vary"].startswith("HX-Request, HX-Target")


def test_nav_marks_current_page(logged_in):
    html = logged_in.get("/reward").text
    assert re.search(r'class="nav-link[^"]*active"\s+href="/reward" aria-current="page"', html)
    assert 'href="/graduation"' in html  # 318 班為高三，顯示畢業學分


def test_exam_page(logged_in):
    html = logged_in.get("/exam").text
    assert "請選擇段考" in html and '<optgroup label="113 學年度上學期">' in html

    html = logged_in.get("/exam?exam=12").text
    t = text(html)
    assert 'value="12" selected' in html
    assert "70.12" in t and "5 / 38" in t
    assert "缺考" in t
    assert 'text-danger fw-semibold">52' in html
    assert logged_in.get("/exam?exam=999").status_code == 404


def test_term_page(logged_in):
    t = text(logged_in.get("/term").text)
    assert "78.5" in t and "30 / 26 / 90" in t and "5 / 30 / 120" in t
    assert "補考分數" not in t
    t = text(logged_in.get("/term?semester=201").text)
    assert "物理" in t and "尚未公布" in t
    assert logged_in.get("/term?semester=abc").status_code == 400


def test_graduation_page(logged_in):
    t = text(logged_in.get("/graduation").text)
    # 已取得：國語文 4（部必）+ 物理 3（校必）+ 音樂 1（校選）
    assert "總學分 8 10 150" in t
    assert "部定必修學分 4 8 80" in t  # 318 班：數理資優班規則


def test_reward_page(logged_in):
    t = text(logged_in.get("/reward").text)
    assert "嘉獎 2 支" in t
    assert "已註銷" in t
    assert "警告 0 支" in t  # 已註銷不計入統計


def test_absence_page(logged_in):
    html = logged_in.get("/absence").text
    t = text(html)
    assert t.index("09/02") < t.index("09/03")
    assert "曠課 2" in t and "遲到 1" in t
    assert 'datetime="2024-09-02"' in html


def test_subject_absence(logged_in):
    t = text(logged_in.get("/subject-absence").text)
    # 週二第 1 節曠課（國語文）、第 2 節事假（數學）、週一第 5 節曠課（英語文）；病假不計
    assert "國語文 1" in t and "數學 1" in t and "英語文 1" in t


def test_school_error_page(logged_in, school):
    school.fail_with = SchoolError(ErrorCode.REMOTE)
    r = logged_in.get("/reward")
    assert r.status_code == 502
    assert "校務系統沒有回應" in r.text
    r = logged_in.get("/reward", headers=HTMX_MAIN)
    assert r.status_code == 502 and "<html" not in r.text


def test_404(client):
    r = client.get("/nope")
    assert r.status_code == 404 and "找不到頁面" in r.text


def test_legacy_redirects(client):
    assert client.get("/tabledownload").headers["location"] == "/documents"
    assert client.get("/exam/").status_code in (307, 308)


def test_healthz(client):
    r = client.get("/healthz")
    assert r.status_code == 200 and r.text == "ok"


def test_manifest(client):
    data = client.get("/manifest.webmanifest").json()
    assert data["start_url"] == "/"
    assert data["icons"][0]["src"] == "/static/icons/android-chrome-192x192.png"


# ---------------------------------------------------------------------- leave & documents


def _leave_data(**overrides):
    data = {
        "reason": "看醫生",
        "leave_type": "3",
        "periods": json.dumps([{"start": "2024-10-02", "end": "2024-10-03", "weekdays": ["3", "1"], "lessons": ["2", "r"]}]),
    }
    data.update(overrides)
    return data


PDF = {"attachment": ("proof.pdf", b"%PDF-1.4", "application/pdf")}


def test_leave_create(logged_in, school):
    r = logged_in.post("/leave", data=_leave_data(), files=PDF, headers={"HX-Request": "true"})
    assert r.status_code == 200
    assert "假單已送出" in r.text
    assert json.loads(r.headers["HX-Trigger"]) == {"leave-changed": {"close": True}}
    _, kwargs = school.calls[-1]
    assert kwargs["from_date"] == "113/10/02" and kwargs["to_date"] == "113/10/03"
    assert kwargs["lessons"] == "r2" and kwargs["weekdays"] == "13"
    assert kwargs["filename"] == "proof.pdf"


def test_leave_create_validation(logged_in, school):
    r = logged_in.post("/leave", data=_leave_data(reason=" "), files=PDF)
    assert "請填寫請假事由" in r.text
    r = logged_in.post("/leave", data=_leave_data(), files={"attachment": ("a.txt", b"x", "text/plain")})
    assert "JPEG、PNG、GIF 或 PDF" in r.text
    bad = json.dumps([{"start": "2024-10-05", "end": "2024-10-03", "weekdays": ["1"], "lessons": ["1"]}])
    r = logged_in.post("/leave", data=_leave_data(periods=bad), files=PDF)
    assert "第 1 個時段：起始日期不能晚於結束日期" in r.text
    bad = json.dumps([{"start": "2024-10-01", "end": "2024-10-03", "weekdays": [], "lessons": ["1"]}])
    r = logged_in.post("/leave", data=_leave_data(periods=bad), files=PDF)
    assert "請至少選擇一個星期" in r.text
    assert "HX-Trigger" not in r.headers
    assert not [c for c in school.calls if c[0] == "add_leave"]


def test_leave_partial_failure(logged_in):
    periods = json.dumps([
        {"start": "2024-10-02", "end": "2024-10-02", "weekdays": ["3"], "lessons": ["1"]},
        {"start": "2024-12-02", "end": "2024-12-02", "weekdays": ["1"], "lessons": ["1"]},
    ])
    r = logged_in.post("/leave", data=_leave_data(periods=periods), files=PDF)
    assert "已送出 1 個時段" in r.text and "第 2 個時段：超過請假期限" in r.text
    assert json.loads(r.headers["HX-Trigger"]) == {"leave-changed": {"close": False}}


def test_leave_list_delete_and_attachment(logged_in, school):
    t = text(logged_in.get("/leave").text)
    assert "看醫生" in t and "待審核" in t and "10/02" in t
    assert logged_in.delete("/leave/9").status_code == 200
    assert ("delete_leave", 9) in school.calls
    assert "這學期沒有任何假單" in logged_in.get("/leave").text
    r = logged_in.get("/leave/9/attachment")
    assert r.content == b"%PDF-1.4" and "proof.pdf" in r.headers["content-disposition"]


def test_background_htmx_error_is_toast(logged_in, school):
    school.fail_with = SchoolError(ErrorCode.REMOTE)
    r = logged_in.get("/documents", headers={"HX-Request": "true", "HX-Target": "leave-list"})
    assert r.headers["HX-Retarget"] == "#toasts"
    assert 'class="toast' in r.text


def test_documents_download(logged_in, school):
    r = logged_in.get("/documents/download?semester=201&kind=grade_table&report_kind=1")
    assert r.status_code == 200 and r.content == b"%PDF-grade"
    assert r.headers["content-type"] == "application/pdf"
    assert "filename*=UTF-8''%E5%AD%B8%E7%94%9F%E6%88%90%E7%B8%BE%E8%A1%A8_1122.pdf" in r.headers["content-disposition"]
    assert school.calls[-1] == ("grade_table", 201, 1)
    assert logged_in.get("/documents/download?semester=201&kind=bogus").status_code == 400
    assert logged_in.get("/documents/download?semester=999&kind=enrolment_certificate").status_code == 404


# ---------------------------------------------------------------------- mounted under a sub path


def test_base_url(school):
    app = create_app(Settings(secret_key="x", base_url="/scoreboard/"), school=school)
    with TestClient(app, follow_redirects=False) as c:
        assert c.get("/").headers["location"] == "/scoreboard/"
        assert c.get("/scoreboard/exam").headers["location"] == "/scoreboard/login?next=%2Fscoreboard%2Fexam"
        html = c.get("/scoreboard/login").text
        assert 'href="/scoreboard/static/vendor/bootstrap.min.css' in html
        assert 'hx-post="/scoreboard/login"' in html
        r = c.post("/scoreboard/login", data={"username": "s", "password": "p", "captcha": "abcd"})
        assert r.headers["location"] == "/scoreboard/exam"
        assert "path=/scoreboard" in r.headers["set-cookie"].lower()
        assert c.get("/scoreboard/exam").status_code == 200
        assert c.get("/scoreboard/static/css/app.css").status_code == 200


def test_login_with_ocr(client, school, monkeypatch):
    from app.school import ocr

    monkeypatch.setattr(ocr, "available", lambda: True)

    async def solve(_):
        return "wxyz"

    monkeypatch.setattr(ocr, "solve", solve)
    html = client.get("/login").text
    assert "改為手動輸入驗證碼" in html and 'name="captcha"' not in html
    r = client.post("/login", data={"username": "s1", "password": "pw"})
    assert r.status_code == 303
    assert school.calls[0] == ("login", "s1", "pw", "wxyz")


def test_ocr_wrong_captcha_falls_back_to_manual(client, school, monkeypatch):
    from app.school import ocr

    monkeypatch.setattr(ocr, "available", lambda: True)

    async def solve(_):
        return "wxyz"

    monkeypatch.setattr(ocr, "solve", solve)
    school.login_error = SchoolError(ErrorCode.WRONG_CAPTCHA)
    r = client.post("/login", data={"username": "s1", "password": "pw"}, headers={"HX-Request": "true"})
    assert "自動辨識驗證碼失敗" in r.text and 'name="captcha"' in r.text
