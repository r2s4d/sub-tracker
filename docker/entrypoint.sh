#!/bin/sh
# Перед запуском gunicorn: применить миграции и собрать статику в общий с nginx том.
# Для разовых команд (`docker compose run web python manage.py ...`) шаги тоже выполняются,
# они идемпотентны: повторный запуск ничего не меняет.
set -e

python manage.py migrate --noinput
python manage.py collectstatic --noinput --verbosity 0

exec "$@"
