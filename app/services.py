"""Pure domain logic on top of the school system data (no I/O)."""

from collections import Counter
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from app.school.codes import COUNTED_ABSENCES
from app.school.models import AbsenceRecord, LeaveEntry, LeaveForm, RewardRecord, Semester, SubjectTermScore


def find_semester(semesters: Sequence[Semester], *, semester_id: int | None = None,
                  year: int | None = None, seme: int | None = None) -> Semester | None:
    """Look up a semester by id or by (year, seme). Falls back to the newest one."""
    for semester in semesters:
        if semester_id is not None and semester.id == semester_id:
            return semester
        if semester_id is None and (semester.year, semester.seme) == (year, seme):
            return semester
    if semester_id is None and year is None and seme is None and semesters:
        return semesters[0]
    return None


def in_semester(records: Iterable[RewardRecord | AbsenceRecord], semester: Semester):
    return [r for r in records if (r.year, r.seme) == (semester.year, semester.seme)]


def reward_totals(records: Iterable[RewardRecord]) -> list[int]:
    totals = [0] * 6
    for record in records:
        if record.cancelled:
            continue
        for i, count in enumerate(record.counts):
            totals[i] += count
    return totals


def absence_totals(records: Iterable[AbsenceRecord]) -> dict[str, int]:
    """Count absences by type code, most frequent first."""
    counter = Counter(code for record in records for code in record.periods if code)
    return dict(counter.most_common())


# AbsenceRecord.periods 的索引 → 課表節次（跳過早修、朝會、午休）
_PERIOD_TO_LESSON = {2: 1, 3: 2, 4: 3, 5: 4, 7: 5, 8: 6, 9: 7, 10: 8}


def subject_absences(records: Iterable[AbsenceRecord], curriculum: dict[int, str]) -> list[tuple[str, int]]:
    """Unexcused absences and personal leave per subject, using the class timetable."""
    counter: Counter[str] = Counter()
    for record in records:
        weekday = record.day.isoweekday()
        for index, lesson in _PERIOD_TO_LESSON.items():
            if record.periods[index] in COUNTED_ABSENCES:
                subject = curriculum.get(weekday * 10 + lesson)
                if subject:
                    counter[subject] += 1
    return counter.most_common()


def group_leave_forms(entries: Iterable[LeaveEntry], semester: Semester) -> list[LeaveForm]:
    forms: dict[int, LeaveForm] = {}
    for entry in entries:
        if entry.semester_id != semester.id:
            continue
        forms.setdefault(entry.leave_id, LeaveForm(entry.leave_id)).days.append(entry)
    for form in forms.values():
        form.days.sort(key=lambda e: e.day)
    return sorted(forms.values(), key=lambda f: f.leave_id, reverse=True)


# ---------------------------------------------------------------------- graduation credits

COURSE_TYPES = ("部必", "校必", "校選")


@dataclass(slots=True)
class Credits:
    national_required: int = 0  # 部定必修
    school_required: int = 0  # 校訂必修
    elective: int = 0  # 選修

    def add(self, course_type: str, credits: int) -> None:
        if course_type == "部必":
            self.national_required += credits
        elif course_type == "校必":
            self.school_required += credits
        elif course_type == "校選":
            self.elective += credits

    def __add__(self, other: "Credits") -> "Credits":
        return Credits(
            self.national_required + other.national_required,
            self.school_required + other.school_required,
            self.elective + other.elective,
        )

    @property
    def required(self) -> int:
        return self.national_required + self.school_required

    @property
    def total(self) -> int:
        return self.required + self.elective


@dataclass(slots=True)
class CreditRequirement:
    label: str
    earned: int
    in_progress: int
    minimum: int

    @property
    def status(self) -> str:
        """``ok``: already met; ``warning``: can be met this semester; ``danger``: cannot be met"""
        if self.earned >= self.minimum:
            return "ok"
        if self.earned + self.in_progress >= self.minimum:
            return "warning"
        return "danger"


def semester_credits(scores: Iterable[SubjectTermScore]) -> tuple[Credits, Credits]:
    """Return ``(attempted, passed)`` credits of one semester."""
    attempted, passed = Credits(), Credits()
    for score in scores:
        attempted.add(score.course_type, score.credits)
        if score.passed:
            passed.add(score.course_type, score.credits)
    return attempted, passed


def graduation_requirements(class_number: int, earned: Credits, current: Credits) -> list[CreditRequirement]:
    """Graduation rules of TNFSH (total 150 credits)."""
    rows = [CreditRequirement("總學分", earned.total, current.total, 150)]
    cls = class_number % 100
    if cls == 18:  # 數理資優班
        rows += [
            CreditRequirement("部定必修學分", earned.national_required, current.national_required, 80),
            CreditRequirement("校訂必修學分", earned.school_required, current.school_required, 24),
            CreditRequirement("選修學分", earned.elective, current.elective, 37),
        ]
    elif cls <= 17 or cls == 19:
        rows += [
            CreditRequirement("必修學分", earned.required, current.required, 102),
            CreditRequirement("選修學分", earned.elective, current.elective, 40),
        ]
    return rows
