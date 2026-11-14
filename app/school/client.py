"""Async client for the school system (校務系統).

Every method raises :class:`app.errors.SchoolError` when the remote server fails,
times out or returns data that cannot be parsed.
"""

import asyncio
import csv
import re
from base64 import b64decode
from typing import Any

import aiohttp
import bs4
import orjson
from fake_useragent import UserAgent

from app.config import Settings
from app.errors import ErrorCode, SchoolError
from app.school.models import (
    AbsenceRecord,
    Attachment,
    Exam,
    ExamResult,
    ExamScore,
    ExamStats,
    LeaveEntry,
    RewardRecord,
    Semester,
    StudentInfo,
    SubjectTermScore,
    TermRanking,
    TermSummary,
)

_SESSION_KEY_RE = re.compile(
    r"<input type=['\"]hidden['\"] name=['\"]session_key['\"] value=['\"](.*?)['\"]\s*/>", re.I
)
_FORM_TOKEN_RE = re.compile(r"name=\"formToken\" value=\"([^\"]*)\"")


def _opt(value: Any) -> str | None:
    """Normalise a value the school system may leave empty."""
    if value is None or value == "":
        return None
    return str(value)


def _opt_int(value: Any) -> int | None:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _periods(obj: dict) -> list[str | None]:
    keys = ("morn", "raiseFlag", "lesson1", "lesson2", "lesson3", "lesson4",
            "rest", "lesson5", "lesson6", "lesson7", "lesson8")
    return [_opt(obj.get(key)) for key in keys]


class SchoolClient:
    def __init__(self, settings: Settings, http: aiohttp.ClientSession | None = None) -> None:
        self.settings = settings
        self._http = http
        self._user_agent = UserAgent()
        self._curriculum_cache: dict[int, dict[int, str]] = {}

    # ------------------------------------------------------------------ lifecycle

    async def start(self) -> None:
        if self._http is None:
            self._http = aiohttp.ClientSession(
                connector=aiohttp.TCPConnector(limit=self.settings.max_connections, ssl=False),
                timeout=aiohttp.ClientTimeout(total=self.settings.request_timeout),
            )

    async def close(self) -> None:
        if self._http is not None:
            await self._http.close()
            self._http = None

    @property
    def http(self) -> aiohttp.ClientSession:
        if self._http is None:
            raise RuntimeError("SchoolClient.start() has not been called")
        return self._http

    # ------------------------------------------------------------------ transport

    def _url(self, action: str) -> str:
        return f"{self.settings.main_url}/{action}"

    async def _request(self, method: str, url: str, *, read: str = "json", **kwargs) -> Any:
        try:
            async with self.http.request(method, url, **kwargs) as resp:
                if not resp.ok:
                    raise SchoolError(ErrorCode.REMOTE)
                if read == "json":
                    return await resp.json(loads=orjson.loads, content_type=None)
                if read == "text":
                    return await resp.text(encoding="utf-8")
                if read == "bytes":
                    return await resp.read()
                if read == "response":
                    return await resp.read(), resp.headers
                raise ValueError(read)
        except SchoolError:
            raise
        except (aiohttp.ClientError, asyncio.TimeoutError, orjson.JSONDecodeError, UnicodeDecodeError) as exc:
            raise SchoolError(ErrorCode.REMOTE) from exc

    async def _post(self, action: str, data: Any = None, *, read: str = "json", **kwargs) -> Any:
        return await self._request("POST", self._url(action), data=data, read=read, **kwargs)

    async def _rows(self, action: str, data: dict) -> list[dict]:
        res = await self._post(action, data)
        if not isinstance(res, dict) or not isinstance(res.get("dataRows"), list):
            raise SchoolError(ErrorCode.REMOTE)
        return res["dataRows"]

    # ------------------------------------------------------------------ login

    async def get_captcha(self) -> str:
        """Return a ``data:image/...;base64,`` captcha picture."""
        res = await self._post("Validate.action")
        if not isinstance(res, dict) or not res.get("src"):
            raise SchoolError(ErrorCode.REMOTE)
        return res["src"]

    async def get_form_token(self) -> str:
        html = await self._request("GET", self.settings.login_url, read="text")
        match = _FORM_TOKEN_RE.search(html)
        if match is None:
            raise SchoolError(ErrorCode.REMOTE)
        return match.group(1)

    async def login(self, username: str, password: str, captcha: str, captcha_src: str = "") -> tuple[str, bool]:
        """Log in and return ``(session_key, password_expired)``.

        The school system asks for a password change every 180 days; the session is still valid
        in that case, so it is reported instead of raised.
        """
        form_token = await self.get_form_token()
        payload = {
            "loginId": username,
            "password": password,
            "validateCode": captcha,
            "validateSrc": captcha_src,
            "schNo": self.settings.school_no,
            "formToken": form_token,
        }
        html = await self._request(
            "POST", self.settings.login_url, data=payload, read="text",
            headers={"User-Agent": self._user_agent.random},
        )

        match = _SESSION_KEY_RE.search(html)
        if match is None:
            if "帳號或密碼錯誤" in html:
                raise SchoolError(ErrorCode.WRONG_CREDENTIALS)
            if "驗證碼錯誤" in html:
                raise SchoolError(ErrorCode.WRONG_CAPTCHA)
            if "錯誤次數過多" in html:
                raise SchoolError(ErrorCode.TOO_MANY_ATTEMPTS)
            raise SchoolError(ErrorCode.GENERAL, "帳號、密碼或驗證碼錯誤")

        return match.group(1), "變更密碼" in html

    async def get_student_info(self, session_key: str) -> StudentInfo:
        """The index page embeds the user as base64 JSON in ``<div id="userInfo">``."""
        data = {"session_key": session_key}
        html = await self._post("Index.action", data, read="text")

        start = html.find('id="userInfo">')
        if start == -1:
            raise SchoolError(ErrorCode.REMOTE)
        start += len('id="userInfo">')
        try:
            user = orjson.loads(b64decode(html[start:html.find("<", start)]))
            student_id = int(user["childId"])
            name = user["name"]
        except (ValueError, KeyError, TypeError) as exc:
            raise SchoolError(ErrorCode.REMOTE) from exc

        res = await self._post("B0410S_StdSemeView_select0410.action", {**data, "pId": student_id})
        info = (res or {}).get("data") or {"seat": "-1", "clsNo": "000-1"}
        return StudentInfo(
            student_id=student_id,
            name=name,
            class_number=_opt_int(str(info.get("clsNo", ""))[3:]) or -1,
            seat_number=_opt_int(info.get("seat")) or -1,
        )

    async def update_password(self, session_key: str, current: str, new: str, confirm: str) -> str | None:
        """Change password; returns ``None`` on success or the school system's message."""
        res = await self._post("changecheck.action", {
            "session_key": session_key,
            "oldpd": current,
            "newpd": new,
            "agnpd": confirm,
        })
        params = res.get("parameterMap") or {}
        if str(params.get("status")) == "200" and not res.get("message"):
            return None
        return res.get("message") or "修改失敗"

    async def forget_password(self, account: str, name: str, id_number: str, birth: str) -> None:
        data = (f"act={account},name={name},idno={id_number},"
                f"schNo={self.settings.school_no},typs=s,birth={birth}")
        try:
            async with self.http.post(self._url("Fta.action"), params={"a": data}, data=data) as resp:
                if not resp.ok:
                    raise SchoolError(ErrorCode.REMOTE)
                try:
                    res = await resp.json(loads=orjson.loads)
                except aiohttp.ContentTypeError as exc:
                    raise SchoolError(ErrorCode.REMOTE_BLOCKED) from exc
        except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
            raise SchoolError(ErrorCode.REMOTE) from exc

        params = res.get("parameterMap") or {}
        if str(params.get("status")) == "200":
            return
        msg = params.get("msg") or ""
        if msg == "無此帳號":
            raise SchoolError(ErrorCode.ACCOUNT_NOT_FOUND)
        if "空白" in msg:
            raise SchoolError(ErrorCode.INVALID_PARAM)
        raise SchoolError(ErrorCode.GENERAL, msg or None)

    # ------------------------------------------------------------------ semesters & exams

    async def get_semesters(self, session_key: str, student_id: int) -> list[Semester]:
        """All semesters of the student, newest first."""
        rows = await self._rows("A0410S_StdSemeView_select.action", {
            "session_key": session_key, "stdId": student_id, "statusM": 15,
        })
        semesters = [Semester(id=int(r["id"]), year=int(r["syear"]), seme=int(r["seme"])) for r in rows]
        return sorted(semesters, key=lambda s: (s.year, s.seme), reverse=True)

    async def get_exams(self, session_key: str, semester: Semester) -> list[Exam]:
        rows = await self._rows("A0410S_Item_select.action", {
            "session_key": session_key, "sidx": "syear,seme,itemNo",
            "syear": semester.year, "seme": semester.seme,
        })
        return [Exam(item_id=int(r["id"]), semester=semester, name=r["name"]) for r in rows]

    async def get_exam_scores(self, session_key: str, exam: Exam) -> list[ExamScore]:
        rows = await self._rows("A0410S_OpenItemScoreView_selectA0410s.action", {
            "session_key": session_key, "itemId": exam.item_id, "stdSemeId": exam.semester.id,
        })
        return [ExamScore(
            subject=r["subjId"],
            credits=_opt_int(r.get("credits")),
            score=_opt(r.get("score")),
            class_average=_opt(r.get("yl")),
            absent=r.get("noExamMark") != "否",
        ) for r in rows]

    async def get_exam_stats(self, session_key: str, exam: Exam) -> ExamStats:
        rows = await self._rows("A0410S_ItemScoreStat_select.action", {
            "session_key": session_key, "itemId": exam.item_id, "stdSemeId": exam.semester.id,
        })
        if not rows:
            return ExamStats()
        r = rows[0]
        return ExamStats(
            class_rank=_opt(r.get("orderC")), class_cnt=_opt(r.get("pnmC")),
            group_rank=_opt(r.get("orderS")), group_cnt=_opt(r.get("pnmS")),
            all_rank=_opt(r.get("orderG")), all_cnt=_opt(r.get("pnmG")),
            score_sum=_opt(r.get("scoreT")), average=_opt(r.get("scoreV")),
        )

    async def get_exam_report(self, session_key: str, exam: Exam) -> ExamResult:
        """Exam scores and statistics parsed from the CSV report (A0492R1).

        The report includes per-subject class/group ranks that the JSON API does not provide.
        """
        year, seme = exam.semester.year, exam.semester.seme
        text = await self._post("A0492R1.action", {
            "session_key": session_key, "syse": f"{year}{seme}", "syear": year, "seme": seme,
            "item": exam.item_id, "item2": exam.item_id, "format": "CSV", "headSign": "false",
            "mail": 5, "showWhat": "on", "showOrd": "on", "showOrd2": "on", "raDt": "",
        }, read="text")
        return parse_exam_report(text)

    async def get_exam_result(self, session_key: str, exam: Exam) -> ExamResult:
        scores, stats, report = await asyncio.gather(
            self.get_exam_scores(session_key, exam),
            self.get_exam_stats(session_key, exam),
            self.get_exam_report(session_key, exam),
            return_exceptions=True,
        )
        for value in (scores, stats):
            if isinstance(value, BaseException):
                raise value

        if isinstance(report, ExamResult):
            by_subject = {s.subject: s for s in report.scores}
            for score in scores:
                if (extra := by_subject.get(score.subject)) is not None:
                    score.class_rank = score.class_rank or extra.class_rank
                    score.group_rank = score.group_rank or extra.group_rank
                    score.class_average = score.class_average or extra.class_average
            stats.fill_missing(report.stats)

        return ExamResult(scores=scores, stats=stats)

    # ------------------------------------------------------------------ term scores

    async def get_term_summaries(self, session_key: str, student_id: int) -> list[TermSummary]:
        rows = await self._rows("A0410S_StdSemeView_select.action", {
            "session_key": session_key, "stdId": student_id, "statusM": 15, "queryKind": "a0410s",
        })
        return [TermSummary(
            semester_id=int(r["id"]),
            score=_opt(r.get("sco6")),
            total_score=_opt(r.get("scoreT")),
            deserved_credits=_opt(r.get("credSum")),
            earned_credits=_opt(r.get("credTot")),
            accumulated_credits=_opt(r.get("credAdd")),
        ) for r in rows]

    async def _term_rows(self, session_key: str, semester_id: int) -> list[dict]:
        return await self._rows("A0410S_OpenStdView_selectA0410s.action", {
            "session_key": session_key, "pId": semester_id,
        })

    async def get_term_scores(self, session_key: str, semester_id: int) -> tuple[list[SubjectTermScore], TermRanking]:
        rows = await self._term_rows(session_key, semester_id)
        scores = [SubjectTermScore(
            subject=r["subjId"],
            course_type=r.get("courseType") or "",
            credits=_opt_int(r.get("credits")) or 0,
            passed=r.get("passYn") == "是",
            score=_opt(r.get("score")),
            score_original=_opt(r.get("scoreSrc")),
            score_makeup=_opt(r.get("scoreExam")),
            score_retake=_opt(r.get("scoreRem")),
            class_average=_opt(r.get("yl")),
            class_rank=_opt(r.get("orderC")),
            group_rank=_opt(r.get("orderS")),
            all_rank=_opt(r.get("orderG")),
        ) for r in rows]

        ranking = TermRanking()
        if rows:
            ranking = TermRanking(
                class_rank=_opt(rows[0].get("orderCQ")),
                group_rank=_opt(rows[0].get("orderSQ")),
                all_rank=_opt(rows[0].get("orderGQ")),
            )
        return scores, ranking

    # ------------------------------------------------------------------ rewards & absences

    async def get_rewards(self, session_key: str) -> list[RewardRecord]:
        rows = await self._rows("B0305S_Reward_select.action", {"session_key": session_key})
        return [RewardRecord(
            year=int(r["syear"]),
            seme=int(r["seme"]),
            fact=r.get("fact") or "",
            description=_opt(r.get("rewardArticleId")),
            counts=tuple(_opt_int(r.get(f"reward{i}")) or 0 for i in range(1, 7)),  # type: ignore[arg-type]
            cancelled=None if not r.get("cancelYn") else r["cancelYn"] != "N",
            cancel_date=_opt(r.get("cancelDt")),
        ) for r in rows]

    async def get_absences(self, session_key: str) -> list[AbsenceRecord]:
        rows = await self._rows("B0209S_Absence_select.action", {"session_key": session_key, "rows": 365 * 3})
        return [AbsenceRecord(
            year=int(r["syear"]),
            seme=int(r["seme"]),
            date=r["absenceDt"],
            periods=_periods(r),
        ) for r in rows]

    async def get_curriculum(self, class_number: int) -> dict[int, str]:
        """Class timetable as ``{weekday * 10 + period: subject}`` (weekday 1–5, period 1–8)."""
        if (cached := self._curriculum_cache.get(class_number)) is not None:
            return cached

        cls = str(class_number)
        year = 106 if cls.endswith("18") else 108 if cls.endswith("19") else 101
        html = await self._request("GET", f"{self.settings.curriculum_url}/C{year}{cls}.HTML", read="bytes")
        try:
            curriculum = parse_curriculum(html)
        except (IndexError, AttributeError) as exc:
            raise SchoolError(ErrorCode.REMOTE, "無法解析班級課表") from exc

        self._curriculum_cache[class_number] = curriculum
        return curriculum

    # ------------------------------------------------------------------ leave requests

    async def get_leave_entries(self, session_key: str) -> list[LeaveEntry]:
        rows = await self._rows("B0207S1_LeaveAction_execute.action", {"session_key": session_key})
        return [LeaveEntry(
            leave_id=int(r["leaveGatId"]),
            semester_id=int(r["stdSemeId"]),
            reviewer=_opt(r.get("examineStatus")),
            status=_opt(r.get("examineM")),
            reason=_opt(r.get("cause")),
            reject_reason=_opt(r.get("causeBack")),
            request_date=_opt(r.get("applyDt")),
            leave_date=r["leaveDt"],
            periods=_periods(r),
        ) for r in rows]

    async def add_leave_request(
        self, session_key: str, student_id: int, *, reason: str, leave_type: str,
        from_date: str, to_date: str, lessons: str, weekdays: str,
        file: bytes, filename: str, content_type: str | None = None,
    ) -> None:
        """Submit one leave period. Dates use the ROC calendar (``113/09/02``)."""
        form = aiohttp.FormData()
        form.add_field("session_key", session_key)
        form.add_field("addIds", str(student_id))
        form.add_field("absenceM", leave_type)
        form.add_field("dt1Q", from_date)
        form.add_field("dt2Q", to_date)
        form.add_field("lesson", lessons)
        form.add_field("dayOfWeek", weekdays)
        form.add_field("cause", reason)
        form.add_field("file", file, filename=filename, content_type=content_type)

        res = await self._post("B0207S1_B0207sAction_add.action", form)
        if (res.get("data") or {}).get("status") == "200":
            return
        raise SchoolError(ErrorCode.GENERAL, res.get("message") or None)

    async def delete_leave_request(self, session_key: str, leave_id: int) -> None:
        await self._post("B0207S1_LeaveGatAction_delete1.action", {
            "session_key": session_key, "id": leave_id, "oper": "del",
        }, read="bytes")

    async def get_leave_attachment(self, session_key: str, leave_id: int) -> Attachment:
        content, headers = await self._post("B0207S1_LeaveGatAction_downloadFile.action", {
            "session_key": session_key, "pid": leave_id,
        }, read="response")
        return Attachment(
            content=content,
            content_type=headers.get("Content-Type", "application/octet-stream"),
            disposition=headers.get("Content-Disposition"),
        )

    # ------------------------------------------------------------------ PDF documents

    async def _pdf(self, action: str, data: dict) -> bytes:
        content, headers = await self._post(action, data, read="response")
        if "pdf" not in headers.get("Content-Type", "pdf").lower() and not content.startswith(b"%PDF"):
            raise SchoolError(ErrorCode.REMOTE, "校務系統沒有產生 PDF，該學期可能沒有資料")
        return content

    async def get_grade_table(self, session_key: str, student_id: int, semester: Semester, report_kind: int) -> bytes:
        return await self._pdf("A0259R1.action", {
            "session_key": session_key, "syse": f"{semester.year}{semester.seme}", "childId": student_id,
            "scoType": 1, "format": "pdf", "rptKind": report_kind, "paperSize": 1,
        })

    async def get_application_grade_table(self, session_key: str, student_id: int, semester: Semester) -> bytes:
        return await self._pdf("A0651R1.action", {
            "session_key": session_key, "syse": f"{semester.year}{semester.seme}", "childId": student_id,
            "opt1": 1, "opt2": 2, "showType": 1, "showType1": 1, "format": "pdf", "rptKind": 1, "paperSize": 1,
        })

    async def get_student_officer_certificate(self, session_key: str, semester: Semester) -> bytes:
        return await self._pdf("B0467R.action", {
            "session_key": session_key, "syse": f"{semester.year}{semester.seme}",
            "opt": 2, "opt1": 1, "opt2": 5, "opt3": 1, "sign": 1,
        })

    async def get_enrolment_certificate(self, session_key: str, semester: Semester) -> bytes:
        return await self._pdf("A0265R2.action", {
            "session_key": session_key, "syse": f"{semester.year}{semester.seme}",
        })


# ---------------------------------------------------------------------- parsers


def parse_exam_report(text: str) -> ExamResult:
    stats = ExamStats()
    scores: list[ExamScore] = []
    finished = False

    def split_rank(cell: str) -> tuple[str | None, str | None]:
        if "/" not in cell:
            return None, None
        rank, count = cell.split("/", 1)
        return _opt(rank.strip()), _opt(count.strip())

    def subject(row: list[str], offset: int, rank_cols: tuple[int, int], avg_col: int) -> ExamScore:
        return ExamScore(
            subject=row[offset].replace("　", "").strip(),
            credits=None,
            score=_opt(row[offset + 5].replace("#", "")),
            class_average=_opt(row[avg_col]),
            absent=False,
            class_rank=_opt(row[rank_cols[0]]),
            group_rank=_opt(row[rank_cols[1]]),
        )

    for idx, row in enumerate(csv.reader(text.splitlines())):
        try:
            if "應修學分" in row:
                stats.score_sum = _opt(row[20])
                stats.average = _opt(row[26])
            elif "全班名次" in row:
                stats.class_rank, stats.class_cnt = split_rank(row[6])
                stats.group_rank, stats.group_cnt = split_rank(row[20])
                stats.all_rank, stats.all_cnt = split_rank(row[32])
                finished = True
            elif idx > 19 and not finished and row and row[0].strip():
                scores.append(subject(row, 0, (9, 12), 15))
                if len(row) > 18 and row[18].strip():  # 兩科並排在同一列
                    scores.append(subject(row, 18, (30, 34), 35))
        except IndexError:
            continue

    return ExamResult(scores=scores, stats=stats)


def parse_curriculum(html: bytes) -> dict[int, str]:
    soup = bs4.BeautifulSoup(html, "html.parser")
    rows = soup.select("table > tr") or soup.select("table tr")
    curriculum: dict[int, str] = {}

    def parse_row(tr: bs4.Tag, period: int) -> None:
        for weekday, td in enumerate(tr.select("td")[2:], start=1):
            teachers = [a.get_text(strip=True) for a in td.select("a")]
            name = ""
            for line in td.get_text().strip().split("\n"):
                if line in teachers or line == "":
                    continue
                for teacher in teachers:
                    line = line.replace(teacher, "")
                name += line
            name = name.strip().replace("\xa0", "")
            if name:
                curriculum[weekday * 10 + period] = name

    # 表格第 4–7 列為第 1–4 節，第 10–13 列為第 5–8 節
    for row_no in range(4, 8):
        parse_row(rows[row_no - 1], row_no - 3)
    for row_no in range(10, 14):
        parse_row(rows[row_no - 1], row_no - 5)
    return curriculum
