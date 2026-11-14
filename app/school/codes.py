"""Code tables used by the school system."""

ABSENCE_SHORT = {
    "1": "曠",
    "2": "事",
    "3": "病",
    "4": "喪",
    "5": "公",
    "7": "遲",
    "E": "退",
    "B": "補",
    "C": "減",
    "N": "抵",
    "O": "空",
    "J": "婚",
    "X": "產前",
    "M": "娩",
    "K": "陪產",
    "Y": "流產",
    "Z": "育嬰",
    "W": "生理",
    "9": "其他",
    "F": "新冠",
    "A": "跨",
    "I": "身心",
}

ABSENCE_LONG = {
    "1": "曠課",
    "2": "事假",
    "3": "病假",
    "4": "喪假",
    "5": "公假",
    "7": "遲到",
    "E": "早退",
    "K": "陪產假",
    "Y": "流產假",
    "Z": "育嬰假",
    "W": "生理假",
    "9": "其他",
    "F": "新冠",
    "I": "身心調適假",
}

LEAVE_REVIEW_STATUS = {
    "0": "未上傳",
    "1": "待審核",
    "Y": "已完成",
    "N": "未通過",
    "B": "退回",
    "R": "重新申請",
}

# 可線上申請的假別
LEAVE_TYPES = {
    "2": "事假",
    "3": "病假",
    "4": "喪假",
    "5": "公假",
    "I": "身心假",
    "W": "生理假",
}

# 線上請假可選的節次（值為校務系統使用的代碼）
LEAVE_LESSONS = {
    "r": "朝會",
    "1": "一",
    "2": "二",
    "3": "三",
    "4": "四",
    "q": "午休",
    "5": "五",
    "6": "六",
    "7": "七",
    "8": "八",
}

# 線上請假可選的星期（0 為星期日）
LEAVE_WEEKDAYS = {
    "1": "一",
    "2": "二",
    "3": "三",
    "4": "四",
    "5": "五",
    "6": "六",
    "0": "日",
}

# 會計入「各科缺席數」的假別：曠課、事假
COUNTED_ABSENCES = frozenset({"1", "2"})


def absence_short(code: str | None) -> str:
    return ABSENCE_SHORT.get(code or "", code or "")


def absence_long(code: str | None) -> str:
    return ABSENCE_LONG.get(code or "", ABSENCE_SHORT.get(code or "", code or ""))


def leave_status(code: str | None) -> str:
    return LEAVE_REVIEW_STATUS.get(code or "", code or "未知")
