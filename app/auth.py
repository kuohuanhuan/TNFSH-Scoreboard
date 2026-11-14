"""Session handling.

The login state lives in a signed, HTTP-only cookie managed by Starlette's ``SessionMiddleware``.
"""

from dataclasses import asdict, dataclass

from fastapi import Depends, Request

from app.errors import LoginRequired
from app.school.client import SchoolClient
from app.school.models import StudentInfo

_SESSION_KEY = "student"


@dataclass(slots=True, frozen=True)
class Student:
    session_key: str
    student_id: int
    name: str
    class_number: int
    seat_number: int

    @property
    def display_name(self) -> str:
        if self.class_number < 0:
            return self.name
        return f"{self.class_number}{self.seat_number:02} {self.name}"

    @property
    def is_senior(self) -> bool:
        """高三才顯示畢業學分"""
        return self.class_number > 300

    @property
    def has_class(self) -> bool:
        return self.class_number > 0 and self.seat_number > 0


def login_user(request: Request, session_key: str, info: StudentInfo) -> Student:
    student = Student(session_key=session_key, **asdict(info))
    request.session.clear()
    request.session[_SESSION_KEY] = asdict(student)
    return student


def logout_user(request: Request) -> None:
    request.session.clear()


def current_student(request: Request) -> Student | None:
    data = request.session.get(_SESSION_KEY)
    if not isinstance(data, dict):
        return None
    try:
        return Student(**data)
    except TypeError:
        request.session.clear()
        return None


def require_student(request: Request) -> Student:
    student = current_student(request)
    if student is None:
        raise LoginRequired
    return student


def get_school(request: Request) -> SchoolClient:
    return request.app.state.school


StudentDep = Depends(require_student)
SchoolDep = Depends(get_school)
