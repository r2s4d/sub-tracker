#!/bin/bash
# Деплой SUb-Tracker на сервере. Вызывается по SSH из GitHub Actions (ключ в authorized_keys
# привязан к этой команде, ничего другого им запустить нельзя), либо руками:
#   /usr/local/bin/subtracker-deploy
#
# Что делает: бэкап базы -> git fetch ветки release -> docker compose up -d --build ->
# проверка, что сайт отвечает -> при неудаче возврат на прошлую версию.
set -euo pipefail

PROJECT=/opt/sub-tracker
BRANCH=release
LOCK=/tmp/subtracker-deploy.lock

# Два деплоя одновременно не нужны: второй ждёт первого до 5 минут.
exec 9>"$LOCK"
flock -w 300 9 || { echo "another deploy is running, giving up"; exit 1; }

cd "$PROJECT"
SITE_URL=$(grep -E '^SITE_URL=' .env | cut -d= -f2-)

# Сайт считается живым, если nginx отвечает 200 или редиректом на вход/https.
wait_for_site() {
    for _ in $(seq 1 30); do
        code=$(curl -s -o /dev/null -w '%{http_code}' -m 5 "$SITE_URL/" || true)
        case "$code" in 200|301|302) echo "site answers $code"; return 0 ;; esac
        sleep 2
    done
    echo "site did not answer in 60 s (last code: $code)"
    return 1
}

PREV=$(git rev-parse HEAD)
git fetch --quiet origin "$BRANCH"
NEW=$(git rev-parse "origin/$BRANCH")
echo "deploy: ${PREV:0:7} -> ${NEW:0:7}"

# Страховка: свежая копия базы до любых изменений (лаба 4).
sudo -n /usr/local/sbin/subtracker-backup.sh

git checkout -q -B "$BRANCH" "origin/$BRANCH"
docker compose up -d --build

if wait_for_site; then
    docker image prune -f >/dev/null   # старые слои сборки занимают диск
    echo "deploy ok: ${NEW:0:7}"
else
    echo "deploy FAILED, rolling back to ${PREV:0:7}"
    git checkout -q -B "$BRANCH" "$PREV"
    docker compose up -d --build
    wait_for_site || echo "rollback did not bring the site back, check manually"
    exit 1
fi
