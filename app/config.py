"""Application settings.

Every value can be overridden with an environment variable prefixed with
``SCOREBOARD_`` (for example ``SCOREBOARD_SECRET_KEY``) or in a ``.env`` file.
"""

import secrets
from functools import lru_cache

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="SCOREBOARD_", env_file=".env", extra="ignore")

    # 校務系統網址與學校代碼
    # https://hschool-mlife.k12ea.gov.tw/ecampus_KH/Login.action?schNo=210305D
    main_url: str = "https://hschool-mlife.k12ea.gov.tw/ecampus_KH"
    school_no: str = "210305D"
    curriculum_url: str = "http://w3.tnfsh.tn.edu.tw/deanofstudies/course"

    # 用來簽署 session cookie 的密鑰。未設定時每次啟動隨機產生（重新啟動後所有人需重新登入）
    secret_key: str = Field(default_factory=lambda: secrets.token_urlsafe(32))

    # 網站掛載路徑，例如 "/scoreboard"
    base_url: str = "/"

    host: str = "0.0.0.0"
    port: int = 5227

    # 與校務系統相同，閒置 30 分鐘後登出
    session_max_age: int = 30 * 60
    # 透過 HTTPS 提供服務時請設為 true
    secure_cookies: bool = False

    request_timeout: float = 20.0
    max_connections: int = 5

    debug: bool = False

    @field_validator("base_url")
    @classmethod
    def _normalise_base_url(cls, value: str) -> str:
        value = "/" + value.strip("/")
        return value

    @field_validator("main_url", "curriculum_url")
    @classmethod
    def _strip_trailing_slash(cls, value: str) -> str:
        return value.rstrip("/")

    @property
    def login_url(self) -> str:
        return f"{self.main_url}/Login.action?schNo={self.school_no}"


@lru_cache
def get_settings() -> Settings:
    return Settings()
