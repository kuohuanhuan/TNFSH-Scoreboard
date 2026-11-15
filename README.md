# TNFSH Scoreboard

## About
學校的成績系統界面對手機使用者不太友善，需要多次點擊與頁面縮放，因此這個項目就誕生了。

功能：段考成績、學期成績、畢業學分試算、缺曠課紀錄、各科缺席數、獎懲紀錄、線上請假、表單（PDF）下載、修改密碼與忘記密碼。

## Project Structure

| 路徑                                          | 說明                                                       |
|:----------------------------------------------|:-----------------------------------------------------------|
| [`app/main.py`](app/main.py)                  | FastAPI 應用程式、錯誤處理、`BASE_URL` 子路徑掛載            |
| [`app/config.py`](app/config.py)              | 設定（環境變數 / `.env`）                                   |
| [`app/school/client.py`](app/school/client.py) | 校務系統的非同步 API client（aiohttp）                      |
| [`app/school/models.py`](app/school/models.py) | 校務系統資料的型別                                          |
| [`app/services.py`](app/services.py)          | 純商業邏輯：統計、各科缺席數、畢業學分                        |
| [`app/routers/`](app/routers)                 | 各頁面的路由                                               |
| [`app/templates/`](app/templates)             | Jinja2 模板（Bootstrap 5 + HTMX + Alpine.js）               |
| [`app/static/`](app/static)                   | CSS、JS、圖示，以及 vendored 的 Bootstrap / HTMX / Alpine.js |
| [`tests/`](tests)                             | pytest 測試（以假的校務系統執行）                            |

### 前端架構

- **伺服器渲染**：每個頁面都是完整的 HTML，不需要 JavaScript 也能瀏覽與查詢。
- **HTMX**：`<body hx-boost>` 讓站內連結與表單只替換 `<main>`；伺服器看到 `HX-Target: main` 時只回傳頁面內容（`layouts/partial.html`），否則回傳完整頁面。
  登入、修改密碼等表單以 `hx-post` 局部更新；背景請求的錯誤會以 toast 顯示。
- **Alpine.js**：只負責純前端的互動，例如顯示密碼、線上請假的多時段表單。
- **Bootstrap 5**：語意化的 HTML（`<nav>`、`<main>`、`<dl>`、`<fieldset>`、`<th scope>`⋯），側邊欄在手機上是 offcanvas，並依系統設定自動切換深色模式。

## Prerequisites

- Python 3.11 以上

## Installation

```shell
git clone https://github.com/tobiichi3227/TNFSH-Scoreboard.git
cd TNFSH-Scoreboard
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -r requirements-ocr.txt
```

`ddddocr` 用來自動辨識登入驗證碼，是選用的；不需要的話改裝 `requirements.txt`，使用者登入時需要手動輸入驗證碼。
也可以使用 `pip install -e ".[ocr]"`。

## Usage

```shell
cp .env.example .env   # 修改 SCOREBOARD_SECRET_KEY
python -m app
```

或直接使用 uvicorn（例如多個 worker 時）：

```shell
uvicorn app.main:app --host 0.0.0.0 --port 5227 --proxy-headers
```

> 多個 worker 或重新啟動後仍要保持登入狀態，必須設定固定的 `SCOREBOARD_SECRET_KEY`。

## Docker

```shell
# 產生固定的密鑰（只需一次），寫進 .env 讓 docker compose 讀取
echo "SCOREBOARD_SECRET_KEY=$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')" > .env
docker compose up -d --build
```

網站會在 <http://localhost:5227>。`compose.yaml` 以唯讀檔案系統、非 root 使用者、移除所有 capabilities 執行，並內建健康檢查（`/healthz`）。

不使用 compose 時：

```shell
docker build -t tnfsh-scoreboard .
docker run -d -p 5227:5227 -e SCOREBOARD_SECRET_KEY=<固定的隨機字串> tnfsh-scoreboard
```

- **不含 OCR 的精簡映像檔**：`docker build --build-arg WITH_OCR=false -t tnfsh-scoreboard:slim .`
  （約 280 MB，含 OCR 約 900 MB），使用者登入時需手動輸入驗證碼。
- **多個 worker**：設定 `WEB_CONCURRENCY=4`。沒有設定 `SCOREBOARD_SECRET_KEY` 時，容器啟動時會產生一組讓所有 worker 共用的暫時密鑰，但重新啟動後所有人都要重新登入。
- **反向代理**：容器預設信任 `X-Forwarded-*` 標頭（`FORWARDED_ALLOW_IPS=*`）。若服務掛在子路徑，設定 `SCOREBOARD_BASE_URL=/scoreboard`；透過 HTTPS 提供服務時設定 `SCOREBOARD_SECURE_COOKIES=true`。

## Configuration

所有設定都可以用 `SCOREBOARD_` 開頭的環境變數或 `.env` 檔覆寫：

| 變數                          | 預設值                                            | 說明                                     |
|:------------------------------|:--------------------------------------------------|:-----------------------------------------|
| `SCOREBOARD_MAIN_URL`         | `https://hschool-mlife.k12ea.gov.tw/ecampus_KH`   | 校務系統的網址                            |
| `SCOREBOARD_SCHOOL_NO`        | `210305D`                                         | 學校代碼                                  |
| `SCOREBOARD_SECRET_KEY`       | 每次啟動隨機產生                                    | 簽署 session cookie 的密鑰                |
| `SCOREBOARD_BASE_URL`         | `/`                                               | 網站掛載的子路徑，例如 `/scoreboard`        |
| `SCOREBOARD_HOST` / `PORT`    | `0.0.0.0` / `5227`                                | `python -m app` 監聽的位址                 |
| `SCOREBOARD_SECURE_COOKIES`   | `false`                                           | 透過 HTTPS 提供服務時設為 `true`           |
| `SCOREBOARD_SESSION_MAX_AGE`  | `1800`                                            | 閒置多久（秒）後登出                       |
| `SCOREBOARD_DEBUG`            | `false`                                           | 開發模式（自動重新載入）                    |

## Development

```shell
pip install -e ".[dev]"
pytest
```

## Contribute
先到 Issues 提 Bug 或 Feature，之後在 PR 上指向之前發的 Issue。
