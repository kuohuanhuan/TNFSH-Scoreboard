#!/bin/sh
set -e

# 沒有設定密鑰時，在啟動前產生一組讓所有 worker 共用。
# 注意：重新啟動容器後所有人都要重新登入；正式環境請設定固定的 SCOREBOARD_SECRET_KEY。
if [ -z "${SCOREBOARD_SECRET_KEY}" ]; then
    SCOREBOARD_SECRET_KEY="$(python -c 'import secrets; print(secrets.token_urlsafe(32))')"
    export SCOREBOARD_SECRET_KEY
    echo "warning: SCOREBOARD_SECRET_KEY is not set; generated a temporary key (sessions reset on restart)" >&2
fi

exec "$@"
