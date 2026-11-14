"""Typed results returned by :class:`app.school.client.SchoolClient`.

Fields that the school system leaves empty (``None`` or ``""``) are normalised to ``None``.
"""

from dataclasses import dataclass, field
from datetime import date

SEMESTER_NAMES = {1: "上", 2: "下"}
REWARD_NAMES = ("嘉獎", "小功", "大功", "警告", "小過", "大過")
# 缺曠課紀錄每一天的 11 個時段
PERIOD_NAMES = ("早修", "朝會", "一", "二", "三", "四", "午休", "五", "六", "七", "八")
WEEKDAY_NAMES = ("一", "二", "三", "四", "五", "六", "日")


def roc_to_date(value: str) -> date:
    """``"113/09/02"`` → ``date(2024, 9, 2)``"""
    year, month, day = (int(part) for part in value.split("/"))
    return date(year + 1911, month, day)


def date_to_roc(value: date) -> str:
    """``date(2024, 9, 2)`` → ``"113/09/02"``"""
    return f"{value.year - 1911}/{value.month:02}/{value.day:02}"


@dataclass(slots=True)
class StudentInfo:
    student_id: int
    name: str
    class_number: int
    seat_number: int


@dataclass(slots=True, frozen=True)
class Semester:
    id: int
    year: int
    seme: int

    @property
    def label(self) -> str:
        return f"{self.year} 學年度{SEMESTER_NAMES.get(self.seme, self.seme)}學期"

    @property
    def key(self) -> str:
        return f"{self.year}-{self.seme}"


@dataclass(slots=True, frozen=True)
class Exam:
    item_id: int
    semester: Semester
    name: str

    @property
    def label(self) -> str:
        return f"{self.semester.year} {SEMESTER_NAMES.get(self.semester.seme, '')} {self.name}"


@dataclass(slots=True)
class ExamScore:
    subject: str
    credits: int | None
    score: str | None
    class_average: str | None
    absent: bool
    class_rank: str | None = None
    group_rank: str | None = None

    @property
    def failed(self) -> bool:
        return _below(self.score, 60)


@dataclass(slots=True)
class ExamStats:
    score_sum: str | None = None
    average: str | None = None
    class_rank: str | None = None
    class_cnt: str | None = None
    group_rank: str | None = None
    group_cnt: str | None = None
    all_rank: str | None = None
    all_cnt: str | None = None

    def fill_missing(self, other: "ExamStats") -> None:
        for name in self.__slots__:
            if getattr(self, name) is None:
                setattr(self, name, getattr(other, name))


@dataclass(slots=True)
class ExamResult:
    scores: list[ExamScore]
    stats: ExamStats


@dataclass(slots=True)
class TermSummary:
    semester_id: int
    score: str | None
    total_score: str | None
    deserved_credits: str | None
    earned_credits: str | None
    accumulated_credits: str | None


@dataclass(slots=True)
class TermRanking:
    class_rank: str | None = None
    group_rank: str | None = None
    all_rank: str | None = None


@dataclass(slots=True)
class SubjectTermScore:
    subject: str
    course_type: str
    credits: int
    passed: bool
    score: str | None
    score_original: str | None
    score_makeup: str | None
    score_retake: str | None
    class_average: str | None
    class_rank: str | None
    group_rank: str | None
    all_rank: str | None

    @property
    def score_level(self) -> str | None:
        """``"danger"`` for 0–39, ``"warning"`` for 40–59, otherwise ``None``"""
        if _below(self.score, 40):
            return "danger"
        if _below(self.score, 60):
            return "warning"
        return None

    @property
    def credits_lost(self) -> bool:
        return self.score is not None and not self.passed


@dataclass(slots=True)
class RewardRecord:
    year: int
    seme: int
    fact: str
    description: str | None
    counts: tuple[int, int, int, int, int, int]
    cancelled: bool | None
    cancel_date: str | None

    @property
    def summary(self) -> str:
        return "、".join(f"{name} {count} 支" for name, count in zip(REWARD_NAMES, self.counts) if count)


@dataclass(slots=True)
class AbsenceRecord:
    year: int
    seme: int
    date: str
    periods: list[str | None]

    @property
    def day(self) -> date:
        return roc_to_date(self.date)

    @property
    def weekday_name(self) -> str:
        return WEEKDAY_NAMES[self.day.weekday()]


@dataclass(slots=True)
class LeaveEntry:
    leave_id: int
    semester_id: int
    reviewer: str | None
    status: str | None
    reason: str | None
    reject_reason: str | None
    request_date: str | None
    leave_date: str
    periods: list[str | None]

    @property
    def day(self) -> date:
        return roc_to_date(self.leave_date)

    @property
    def weekday_name(self) -> str:
        return WEEKDAY_NAMES[self.day.weekday()]


@dataclass(slots=True)
class LeaveForm:
    """One leave request (假單) spans one or more days."""

    leave_id: int
    days: list[LeaveEntry] = field(default_factory=list)

    @property
    def first(self) -> LeaveEntry:
        return self.days[0]


@dataclass(slots=True)
class Attachment:
    content: bytes
    content_type: str
    disposition: str | None


def _below(value: str | None, threshold: float) -> bool:
    if value is None:
        return False
    try:
        return float(value) < threshold
    except ValueError:
        return False
