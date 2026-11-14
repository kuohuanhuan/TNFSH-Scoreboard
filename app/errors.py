from enum import StrEnum


class ErrorCode(StrEnum):
    GENERAL = "general"
    ACCOUNT_NOT_FOUND = "account_not_found"
    WRONG_CREDENTIALS = "wrong_credentials"
    WRONG_CAPTCHA = "wrong_captcha"
    TOO_MANY_ATTEMPTS = "too_many_attempts"
    OCR_UNAVAILABLE = "ocr_unavailable"
    INVALID_PARAM = "invalid_param"
    REMOTE = "remote"
    REMOTE_BLOCKED = "remote_blocked"


MESSAGES: dict[ErrorCode, str] = {
    ErrorCode.GENERAL: "發生未知錯誤，請稍後再試",
    ErrorCode.ACCOUNT_NOT_FOUND: "帳號不存在",
    ErrorCode.WRONG_CREDENTIALS: "帳號或密碼錯誤",
    ErrorCode.WRONG_CAPTCHA: "驗證碼錯誤",
    ErrorCode.TOO_MANY_ATTEMPTS: "錯誤次數過多，校務系統鎖定 15 分鐘無法登入",
    ErrorCode.OCR_UNAVAILABLE: "無法自動辨識驗證碼，請手動輸入",
    ErrorCode.INVALID_PARAM: "輸入資料錯誤",
    ErrorCode.REMOTE: "校務系統沒有回應或回傳了無法解析的資料，請稍後再試",
    ErrorCode.REMOTE_BLOCKED: "校務系統暫時封鎖連線，請稍後再試",
}


class SchoolError(Exception):
    """An expected failure while talking to the school system."""

    def __init__(self, code: ErrorCode, detail: str | None = None) -> None:
        self.code = code
        self.detail = detail
        super().__init__(self.message)

    @property
    def message(self) -> str:
        return self.detail or MESSAGES[self.code]


class LoginRequired(Exception):
    """Raised by the auth dependency when there is no valid session."""
