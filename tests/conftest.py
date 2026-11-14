import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.errors import ErrorCode, SchoolError
from app.main import create_app
from app.school import ocr
from app.school.client import SchoolClient
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

SEM_NEW = Semester(id=202, year=113, seme=1)
SEM_OLD = Semester(id=201, year=112, seme=2)
NO_ABSENCE = [None] * 11


def _term_score(subject, course_type, credits, score, passed=True):
    return SubjectTermScore(subject, course_type, credits, passed, score, score, None, None, "70", "3", "10", "50")


class FakeSchool(SchoolClient):
    """In-memory stand-in for the school system."""

    def __init__(self):
        super().__init__(Settings(secret_key="test"), http=None)
        self.calls: list[tuple] = []
        self.fail_with: SchoolError | None = None
        self.login_error: SchoolError | None = None
        self.password_expired = False
        self.leave_entries = [
            LeaveEntry(9, SEM_NEW.id, None, "1", "看醫生", None, "113/10/01", "113/10/02",
                       [None, None, "3", "3", None, None, None, None, None, None, None]),
        ]

    async def start(self):
        pass

    async def close(self):
        pass

    def _check(self):
        if self.fail_with:
            raise self.fail_with

    async def get_captcha(self):
        return "data:image/png;base64,iVBORw0KGgo="

    async def login(self, username, password, captcha, captcha_src=""):
        self.calls.append(("login", username, password, captcha))
        if self.login_error:
            raise self.login_error
        return "session-key", self.password_expired

    async def get_student_info(self, session_key):
        return StudentInfo(student_id=1001, name="王小明", class_number=318, seat_number=7)

    async def get_semesters(self, session_key, student_id):
        self._check()
        return [SEM_NEW, SEM_OLD]

    async def get_exams(self, session_key, semester):
        if semester == SEM_NEW:
            return [Exam(11, semester, "第一次期中考"), Exam(12, semester, "第二次期中考")]
        return [Exam(5, semester, "期末考")]

    async def get_exam_result(self, session_key, exam):
        return ExamResult(
            scores=[
                ExamScore("國語文", 4, "88", "75.5", False, "3", "20"),
                ExamScore("數學", 4, "52", "60", False),
                ExamScore("英語文", 4, None, None, True),
            ],
            stats=ExamStats(score_sum="140", average="70.123", class_rank="5", class_cnt="38"),
        )

    async def get_term_scores(self, session_key, semester_id):
        if semester_id == SEM_NEW.id:
            return [
                _term_score("國語文", "部必", 4, "85"),
                _term_score("數學", "部必", 4, "35", passed=False),
                _term_score("專題", "校選", 2, None, passed=False),
            ], TermRanking("5", "30", "120")
        return [_term_score("物理", "校必", 3, "77"), _term_score("音樂", "校選", 1, "90")], TermRanking()

    async def get_term_summaries(self, session_key, student_id):
        return [TermSummary(SEM_NEW.id, "78.456", "700", "30", "26", "90")]

    async def get_rewards(self, session_key):
        return [
            RewardRecord(113, 1, "擔任幹部", "服務熱心", (2, 0, 0, 0, 0, 0), False, None),
            RewardRecord(113, 1, "遲到", None, (0, 0, 0, 1, 0, 0), True, "113/12/01"),
            RewardRecord(112, 2, "比賽", None, (0, 1, 0, 0, 0, 0), None, None),
        ]

    async def get_absences(self, session_key):
        return [
            AbsenceRecord(113, 1, "113/09/03", [None, None, "1", "2", None, None, None, "3", None, None, None]),  # 週二
            AbsenceRecord(113, 1, "113/09/02", [None, "7", None, None, None, None, None, "1", None, None, None]),  # 週一
            AbsenceRecord(112, 2, "113/03/04", ["1"] + NO_ABSENCE[1:]),
        ]

    async def get_curriculum(self, class_number):
        return {21: "國語文", 22: "數學", 15: "英語文"}

    async def get_leave_entries(self, session_key):
        return list(self.leave_entries)

    async def add_leave_request(self, session_key, student_id, **kwargs):
        self.calls.append(("add_leave", kwargs))
        if kwargs["from_date"].startswith("113/12"):
            raise SchoolError(ErrorCode.GENERAL, "超過請假期限")

    async def delete_leave_request(self, session_key, leave_id):
        self.calls.append(("delete_leave", leave_id))
        self.leave_entries = [e for e in self.leave_entries if e.leave_id != leave_id]

    async def get_leave_attachment(self, session_key, leave_id):
        return Attachment(b"%PDF-1.4", "application/pdf", 'attachment; filename="proof.pdf"')

    async def get_grade_table(self, session_key, student_id, semester, report_kind):
        self.calls.append(("grade_table", semester.id, report_kind))
        return b"%PDF-grade"

    async def get_enrolment_certificate(self, session_key, semester):
        return b"%PDF-enrol"

    async def update_password(self, session_key, current, new, confirm):
        self.calls.append(("update_password", current, new))
        return None

    async def forget_password(self, account, name, id_number, birth):
        self.calls.append(("forget_password", account, name, id_number, birth))


@pytest.fixture
def school():
    return FakeSchool()


@pytest.fixture(autouse=True)
def no_ocr(monkeypatch):
    monkeypatch.setattr(ocr, "available", lambda: False)


@pytest.fixture
def client(school):
    app = create_app(Settings(secret_key="test-secret"), school=school)
    with TestClient(app, follow_redirects=False) as c:
        yield c


@pytest.fixture
def logged_in(client):
    r = client.post("/login", data={"username": "s1", "password": "pw", "captcha": "abcd"})
    assert r.status_code == 303, r.text
    return client


HTMX_MAIN = {"HX-Request": "true", "HX-Target": "main"}
