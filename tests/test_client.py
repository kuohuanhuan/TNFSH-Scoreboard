"""SchoolClient against a local fake of the school system."""

import asyncio
import base64
import json

import orjson
import pytest
from aiohttp import web

from app.config import Settings
from app.errors import ErrorCode, SchoolError
from app.school.client import SchoolClient, parse_curriculum, parse_exam_report
from app.school.models import Exam, Semester

USER_INFO = base64.b64encode(json.dumps({"childId": "1001", "name": "王小明"}).encode()).decode()


def _report_csv() -> str:
    rows = [[""] * 40 for _ in range(20)]
    subject = [""] * 36
    subject[0], subject[5], subject[9], subject[12], subject[15] = "國　文", "88#", "3", "20", "75.5"
    subject[18], subject[23], subject[30], subject[34], subject[35] = "數學", "52", "15", "100", "60"
    total = [""] * 40
    total[0], total[20], total[26] = "應修學分", "140", "70.12"
    ranks = [""] * 40
    ranks[0], ranks[6], ranks[20], ranks[32] = "全班名次", "5/38", "30/300", "120/900"
    rows += [subject, total, ranks]
    return "\n".join(",".join(r) for r in rows)


def make_app(received: dict) -> web.Application:
    async def form(request):
        data = await request.post()
        received[request.path] = dict(data)
        return data

    async def login_page(request):
        return web.Response(text='<input type="hidden" name="formToken" value="tok123">', content_type="text/html")

    async def login_post(request):
        data = await form(request)
        if data["password"] == "wrong":
            return web.Response(text="帳號或密碼錯誤", content_type="text/html")
        extra = "請變更密碼" if data["password"] == "old" else ""
        return web.Response(text=f"<input type='hidden' name='session_key' value='KEY'/>{extra}", content_type="text/html")

    async def index(request):
        await form(request)
        return web.Response(text=f'<div style="display: none;" id="userInfo">{USER_INFO}</div>', content_type="text/html")

    async def seat(request):
        await form(request)
        return web.json_response({"data": {"seat": "07", "clsNo": "113318"}})

    async def semesters(request):
        await form(request)
        return web.json_response({"dataRows": [
            {"id": 201, "syear": 112, "seme": 2, "grade": 2},
            {"id": 202, "syear": 113, "seme": 1, "grade": 3},
        ]})

    async def scores(request):
        await form(request)
        # 校務系統常以 text/html 回傳 JSON
        body = orjson.dumps({"dataRows": [
            {"subjId": "國文", "score": 88, "yl": None, "noExamMark": "否", "credits": "4"},
            {"subjId": "數學", "score": "", "yl": "60", "noExamMark": "否", "credits": 4},
        ]})
        return web.Response(body=body, content_type="text/html")

    async def stats(request):
        await form(request)
        return web.json_response({"dataRows": []})

    async def report(request):
        await form(request)
        return web.Response(text=_report_csv())

    async def broken(request):
        return web.Response(text="<html>session expired</html>", content_type="text/html")

    async def pdf(request):
        await form(request)
        return web.Response(body=b"%PDF-1.4 ...", content_type="application/pdf")

    app = web.Application()
    app.router.add_get("/ecampus/Login.action", login_page)
    app.router.add_post("/ecampus/Login.action", login_post)
    app.router.add_post("/ecampus/Index.action", index)
    app.router.add_post("/ecampus/B0410S_StdSemeView_select0410.action", seat)
    app.router.add_post("/ecampus/A0410S_StdSemeView_select.action", semesters)
    app.router.add_post("/ecampus/A0410S_OpenItemScoreView_selectA0410s.action", scores)
    app.router.add_post("/ecampus/A0410S_ItemScoreStat_select.action", stats)
    app.router.add_post("/ecampus/A0492R1.action", report)
    app.router.add_post("/ecampus/B0305S_Reward_select.action", broken)
    app.router.add_post("/ecampus/A0265R2.action", pdf)
    return app


def run(coro_fn):
    async def main():
        received: dict = {}
        runner = web.AppRunner(make_app(received))
        await runner.setup()
        site = web.TCPSite(runner, "127.0.0.1", 0)
        await site.start()
        port = site._server.sockets[0].getsockname()[1]
        client = SchoolClient(Settings(secret_key="x", main_url=f"http://127.0.0.1:{port}/ecampus"))
        await client.start()
        try:
            await coro_fn(client, received)
        finally:
            await client.close()
            await runner.cleanup()

    asyncio.run(main())


def test_login_and_student_info():
    async def check(client: SchoolClient, received):
        key, expired = await client.login("s1", "pw", "abcd")
        assert (key, expired) == ("KEY", False)
        assert received["/ecampus/Login.action"]["formToken"] == "tok123"
        assert received["/ecampus/Login.action"]["validateCode"] == "abcd"
        assert (await client.login("s1", "old", "abcd"))[1] is True
        with pytest.raises(SchoolError) as exc:
            await client.login("s1", "wrong", "abcd")
        assert exc.value.code == ErrorCode.WRONG_CREDENTIALS

        info = await client.get_student_info("KEY")
        assert (info.student_id, info.name, info.class_number, info.seat_number) == (1001, "王小明", 318, 7)
        assert received["/ecampus/B0410S_StdSemeView_select0410.action"]["pId"] == "1001"

    run(check)


def test_semesters_and_exam_result():
    async def check(client: SchoolClient, received):
        semesters = await client.get_semesters("KEY", 1001)
        assert [s.id for s in semesters] == [202, 201]  # 新的在前
        assert received["/ecampus/A0410S_StdSemeView_select.action"]["statusM"] == "15"

        exam = Exam(11, semesters[0], "第一次期中考")
        result = await client.get_exam_result("KEY", exam)
        chinese, math = result.scores
        assert (chinese.score, chinese.class_average, chinese.class_rank, chinese.group_rank) == ("88", "75.5", "3", "20")
        assert (math.score, math.class_rank, math.group_rank) == (None, "15", "100")
        # 統計尚未公布時以報表補上
        assert (result.stats.score_sum, result.stats.class_rank, result.stats.all_cnt) == ("140", "5", "900")
        assert received["/ecampus/A0492R1.action"]["syse"] == "1131"

    run(check)


def test_unparseable_response_is_remote_error():
    async def check(client: SchoolClient, _):
        with pytest.raises(SchoolError) as exc:
            await client.get_rewards("KEY")
        assert exc.value.code == ErrorCode.REMOTE

    run(check)


def test_pdf():
    async def check(client: SchoolClient, _):
        assert (await client.get_enrolment_certificate("KEY", Semester(1, 113, 1))).startswith(b"%PDF")

    run(check)


def test_unreachable_server():
    async def main():
        client = SchoolClient(Settings(secret_key="x", main_url="http://127.0.0.1:9/ecampus", request_timeout=2))
        await client.start()
        try:
            with pytest.raises(SchoolError):
                await client.get_captcha()
        finally:
            await client.close()

    asyncio.run(main())


def test_parse_exam_report_tolerates_short_rows():
    result = parse_exam_report("a,b\n" * 25)
    assert result.scores == [] and result.stats.class_rank is None


def test_parse_curriculum():
    cell = lambda name: f"<td>{name}<br><a>王老師</a></td>"
    rows = ["<tr><td>x</td></tr>"] * 3
    rows += [f"<tr><td>{p}</td><td>t</td>{cell('國文')}{cell('數學')}<td>&nbsp;</td></tr>" for p in range(1, 5)]
    rows += ["<tr><td>x</td></tr>"] * 2
    rows += [f"<tr><td>{p}</td><td>t</td>{cell('英文')}</tr>" for p in range(5, 9)]
    curriculum = parse_curriculum(f"<table>{''.join(rows)}</table>".encode())
    assert curriculum[11] == "國文" and curriculum[21] == "數學" and curriculum[15] == "英文"
    assert 31 not in curriculum
