import asyncio
import json
from datetime import date
from typing import Annotated, Literal
from urllib.parse import quote

from fastapi import APIRouter, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, Field, TypeAdapter, ValidationError, model_validator

from app.auth import SchoolDep, StudentDep, Student
from app.errors import SchoolError
from app.school import codes
from app.school.client import SchoolClient
from app.school.models import Semester, date_to_roc
from app.services import (
    absence_totals,
    find_semester,
    group_leave_forms,
    in_semester,
    reward_totals,
    subject_absences,
)
from app.templating import render, templates

router = APIRouter()


def _pick(semesters: list[Semester], semester_id: int | None) -> Semester | None:
    selected = find_semester(semesters, semester_id=semester_id)
    if selected is None and semester_id is not None:
        raise HTTPException(404)
    return selected


# ---------------------------------------------------------------------- rewards & absences


@router.get("/reward", name="reward")
async def reward_page(request: Request, semester: int | None = None,
                      student: Student = StudentDep, school: SchoolClient = SchoolDep):
    semesters, rewards = await asyncio.gather(
        school.get_semesters(student.session_key, student.student_id),
        school.get_rewards(student.session_key),
    )
    selected = _pick(semesters, semester)
    records = in_semester(rewards, selected) if selected else []
    return render(request, "pages/reward.html", {
        "active": "reward",
        "semesters": semesters,
        "selected": selected,
        "records": records,
        "totals": reward_totals(records),
    })


@router.get("/absence", name="absence")
async def absence_page(request: Request, semester: int | None = None,
                       student: Student = StudentDep, school: SchoolClient = SchoolDep):
    semesters, absences = await asyncio.gather(
        school.get_semesters(student.session_key, student.student_id),
        school.get_absences(student.session_key),
    )
    selected = _pick(semesters, semester)
    records = sorted(in_semester(absences, selected), key=lambda r: r.day) if selected else []
    return render(request, "pages/absence.html", {
        "active": "absence",
        "semesters": semesters,
        "selected": selected,
        "records": records,
        "totals": absence_totals(records),
    })


@router.get("/subject-absence", name="subject_absence")
async def subject_absence_page(request: Request, student: Student = StudentDep, school: SchoolClient = SchoolDep):
    ctx: dict = {"active": "subject_absence", "counts": [], "semester": None}
    if student.has_class:
        semesters, absences, curriculum = await asyncio.gather(
            school.get_semesters(student.session_key, student.student_id),
            school.get_absences(student.session_key),
            school.get_curriculum(student.class_number),
        )
        if semesters:
            ctx["semester"] = semesters[0]
            ctx["counts"] = subject_absences(in_semester(absences, semesters[0]), curriculum)
    return render(request, "pages/subject_absence.html", ctx)


# ---------------------------------------------------------------------- leave requests


@router.get("/leave", name="leave")
async def leave_page(request: Request, semester: int | None = None,
                     student: Student = StudentDep, school: SchoolClient = SchoolDep):
    semesters, entries = await asyncio.gather(
        school.get_semesters(student.session_key, student.student_id),
        school.get_leave_entries(student.session_key),
    )
    selected = _pick(semesters, semester)
    return render(request, "pages/leave.html", {
        "active": "leave",
        "semesters": semesters,
        "selected": selected,
        "forms": group_leave_forms(entries, selected) if selected else [],
    })


MAX_ATTACHMENT_SIZE = 5 * 1024 * 1024
ALLOWED_ATTACHMENT_TYPES = {"image/jpeg", "image/png", "image/gif", "application/pdf"}

Weekday = Literal[tuple(codes.LEAVE_WEEKDAYS)]  # type: ignore[valid-type]
Lesson = Literal[tuple(codes.LEAVE_LESSONS)]  # type: ignore[valid-type]


class LeavePeriod(BaseModel):
    start: date
    end: date
    weekdays: list[Weekday] = Field(min_length=1)
    lessons: list[Lesson] = Field(min_length=1)

    @model_validator(mode="after")
    def _check_range(self):
        if self.start > self.end:
            raise ValueError("起始日期不能晚於結束日期")
        return self

    def codes_in_order(self, field: str, table: dict[str, str]) -> str:
        chosen = set(getattr(self, field))
        return "".join(code for code in table if code in chosen)


_PERIODS = TypeAdapter(list[LeavePeriod])


def _parse_periods(raw: str) -> tuple[list[LeavePeriod], str | None]:
    try:
        periods = _PERIODS.validate_python(json.loads(raw or "[]"))
    except json.JSONDecodeError:
        return [], "請假時段格式錯誤"
    except ValidationError as exc:
        err = exc.errors()[0]
        index = err["loc"][0] + 1 if err["loc"] and isinstance(err["loc"][0], int) else "?"
        field = err["loc"][1] if len(err["loc"]) > 1 else None
        message = {
            "start": "請選擇起始日期", "end": "請選擇結束日期",
            "weekdays": "請至少選擇一個星期", "lessons": "請至少選擇一個節次",
        }.get(field, err["msg"].removeprefix("Value error, "))
        return [], f"第 {index} 個時段：{message}"
    if not periods:
        return [], "請至少新增一個請假時段"
    return periods, None


def _leave_feedback(request: Request, *, error: str | None = None, failures: list[str] | None = None,
                    succeeded: int = 0, headers: dict | None = None) -> Response:
    return templates.TemplateResponse(request, "partials/leave_feedback.html", {
        "error": error, "failures": failures or [], "succeeded": succeeded,
    }, headers=headers)


@router.post("/leave", name="leave_create")
async def leave_create(
    request: Request,
    reason: Annotated[str, Form()] = "",
    leave_type: Annotated[str, Form()] = "",
    periods: Annotated[str, Form()] = "[]",
    attachment: Annotated[UploadFile | None, File()] = None,
    student: Student = StudentDep,
    school: SchoolClient = SchoolDep,
):
    reason = reason.strip()
    if not reason:
        return _leave_feedback(request, error="請填寫請假事由")
    if leave_type not in codes.LEAVE_TYPES:
        return _leave_feedback(request, error="請選擇請假類型")
    if attachment is None or not attachment.filename:
        return _leave_feedback(request, error="請上傳證明文件")
    if attachment.content_type not in ALLOWED_ATTACHMENT_TYPES:
        return _leave_feedback(request, error="證明文件只能是 JPEG、PNG、GIF 或 PDF 檔")
    content = await attachment.read(MAX_ATTACHMENT_SIZE + 1)
    if len(content) > MAX_ATTACHMENT_SIZE:
        return _leave_feedback(request, error="證明文件不可大於 5 MiB")

    parsed, error = _parse_periods(periods)
    if error:
        return _leave_feedback(request, error=error)

    failures: list[str] = []
    for index, period in enumerate(parsed, start=1):
        try:
            await school.add_leave_request(
                student.session_key, student.student_id,
                reason=reason, leave_type=leave_type,
                from_date=date_to_roc(period.start), to_date=date_to_roc(period.end),
                lessons=period.codes_in_order("lessons", codes.LEAVE_LESSONS),
                weekdays=period.codes_in_order("weekdays", codes.LEAVE_WEEKDAYS),
                file=content, filename=attachment.filename, content_type=attachment.content_type,
            )
        except SchoolError as exc:
            failures.append(f"第 {index} 個時段：{exc.message}")

    succeeded = len(parsed) - len(failures)
    headers = None
    if succeeded:
        headers = {"HX-Trigger": json.dumps({"leave-changed": {"close": not failures}})}
    return _leave_feedback(request, failures=failures, succeeded=succeeded, headers=headers)


@router.delete("/leave/{leave_id}", name="leave_delete")
async def leave_delete(leave_id: int, student: Student = StudentDep, school: SchoolClient = SchoolDep):
    await school.delete_leave_request(student.session_key, leave_id)
    # 刪除的卡片直接移除，同時通知列表重新整理（例如顯示「沒有假單」）
    return Response(status_code=200, headers={"HX-Trigger": json.dumps({"leave-changed": {"close": False}})})


def _content_disposition(filename: str) -> str:
    fallback = filename.encode("ascii", "replace").decode().replace("?", "_").replace('"', "")
    return f"attachment; filename=\"{fallback}\"; filename*=UTF-8''{quote(filename)}"


@router.get("/leave/{leave_id}/attachment", name="leave_attachment")
async def leave_attachment(leave_id: int, student: Student = StudentDep, school: SchoolClient = SchoolDep):
    file = await school.get_leave_attachment(student.session_key, leave_id)
    disposition = file.disposition or _content_disposition(f"假單證明_{leave_id}")
    return Response(file.content, media_type=file.content_type, headers={"Content-Disposition": disposition})


# ---------------------------------------------------------------------- PDF documents

DOCUMENTS = {
    "application_grade_table": "申請用學期成績單",
    "grade_table": "學生成績表",
    "student_officer_certificate": "學生幹部證明",
    "enrolment_certificate": "在學證明",
}

GRADE_TABLE_KINDS = {
    0: "雙頁表格：沒有學籍表，含重考與原始成績、加權總分及年級人數",
    1: "單頁表格：含學籍表，成績為最後成績（已整合重考與原始成績），含年級人數，無加權總分",
}


@router.get("/documents", name="documents")
async def documents_page(request: Request, student: Student = StudentDep, school: SchoolClient = SchoolDep):
    semesters = await school.get_semesters(student.session_key, student.student_id)
    return render(request, "pages/documents.html", {
        "active": "documents",
        "semesters": semesters,
        "documents": DOCUMENTS,
        "grade_table_kinds": GRADE_TABLE_KINDS,
    })


@router.get("/documents/download", name="documents_download")
async def documents_download(
    semester: int,
    kind: Literal[tuple(DOCUMENTS)],  # type: ignore[valid-type]
    report_kind: Annotated[int, Query(ge=0, le=1)] = 0,
    student: Student = StudentDep,
    school: SchoolClient = SchoolDep,
):
    semesters = await school.get_semesters(student.session_key, student.student_id)
    selected = _pick(semesters, semester)
    key, sid = student.session_key, student.student_id

    if kind == "application_grade_table":
        pdf = await school.get_application_grade_table(key, sid, selected)
    elif kind == "grade_table":
        pdf = await school.get_grade_table(key, sid, selected, report_kind)
    elif kind == "student_officer_certificate":
        pdf = await school.get_student_officer_certificate(key, selected)
    else:
        pdf = await school.get_enrolment_certificate(key, selected)

    filename = f"{DOCUMENTS[kind]}_{selected.year}{selected.seme}.pdf"
    return Response(pdf, media_type="application/pdf", headers={
        "Content-Disposition": _content_disposition(filename),
        "Cache-Control": "no-store",
    })
