import asyncio
from itertools import groupby

from fastapi import APIRouter, HTTPException, Request

from app.auth import SchoolDep, StudentDep, Student
from app.school.client import SchoolClient
from app.services import Credits, find_semester, graduation_requirements, semester_credits
from app.templating import render

router = APIRouter()


@router.get("/exam", name="exam")
async def exam_page(request: Request, exam: int | None = None,
                    student: Student = StudentDep, school: SchoolClient = SchoolDep):
    key = student.session_key
    semesters = await school.get_semesters(key, student.student_id)
    exams = [e for group in await asyncio.gather(*(school.get_exams(key, s) for s in semesters)) for e in group]

    selected = next((e for e in exams if e.item_id == exam), None)
    if exam is not None and selected is None:
        raise HTTPException(404)
    result = await school.get_exam_result(key, selected) if selected else None

    return render(request, "pages/exam.html", {
        "active": "exam",
        "exam_groups": [(sem, list(items)) for sem, items in groupby(exams, key=lambda e: e.semester)],
        "selected": selected,
        "result": result,
    })


@router.get("/term", name="term")
async def term_page(request: Request, semester: int | None = None,
                    student: Student = StudentDep, school: SchoolClient = SchoolDep):
    key = student.session_key
    semesters = await school.get_semesters(key, student.student_id)
    selected = find_semester(semesters, semester_id=semester)
    if selected is None and semester is not None:
        raise HTTPException(404)

    scores, ranking, summary = [], None, None
    if selected is not None:
        (scores, ranking), summaries = await asyncio.gather(
            school.get_term_scores(key, selected.id),
            school.get_term_summaries(key, student.student_id),
        )
        summary = next((s for s in summaries if s.semester_id == selected.id), None)

    return render(request, "pages/term.html", {
        "active": "term",
        "semesters": semesters,
        "selected": selected,
        "scores": scores,
        "ranking": ranking,
        "summary": summary,
        "show_makeup": any(s.score_makeup for s in scores),
        "show_retake": any(s.score_retake for s in scores),
    })


@router.get("/graduation", name="graduation")
async def graduation_page(request: Request, student: Student = StudentDep, school: SchoolClient = SchoolDep):
    key = student.session_key
    semesters = await school.get_semesters(key, student.student_id)
    results = await asyncio.gather(*(school.get_term_scores(key, s.id) for s in semesters), return_exceptions=True)

    earned, current = Credits(), Credits()
    for semester, result in zip(semesters, results):
        if isinstance(result, BaseException):
            continue
        attempted, passed = semester_credits(result[0])
        earned += passed
        if semester == semesters[0]:
            current = attempted

    return render(request, "pages/graduation.html", {
        "active": "graduation",
        "current": current,
        "requirements": graduation_requirements(student.class_number, earned, current) if earned.total else [],
    })
