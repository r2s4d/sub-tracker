# Subscription Tracker

Веб-приложение для учёта личных подписок: стриминг, связь, хостинг, SaaS и т.д.
Показывает расходы по категориям, динамику по месяцам, ближайшие продления
и напоминает на почту об окончании пробного периода.

**Стек:** Django (server-side шаблоны) · PostgreSQL · Bootstrap · Chart.js · Docker

## Локальный запуск

```bash
python -m venv .venv
.venv\Scripts\activate          # Windows; на Linux/macOS: source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env            # заполнить значения
docker compose up -d db         # PostgreSQL

python manage.py migrate
python manage.py createsuperuser
python manage.py runserver
```

## Запуск на сервере (Docker)

```
Интернет ──> nginx :80 ──> web (gunicorn + Django) :8000 ──> db (PostgreSQL)
               │
               └── /static/ отдаёт сам из общего тома
```

```bash
git clone https://github.com/r2s4d/sub-tracker.git && cd sub-tracker
cp .env.example .env    # DJANGO_DEBUG=false, свой DJANGO_SECRET_KEY, пароль базы,
                        # DJANGO_ALLOWED_HOSTS и SITE_URL с адресом сервера
docker compose up -d --build
docker compose exec web python manage.py createsuperuser
docker compose exec web python manage.py seed_demo      # пользователь demo / demo12345
```

Миграции и `collectstatic` выполняются при каждом старте контейнера `web`.
Обновление: `git pull && docker compose up -d --build`.

Напоминания об окончании триала: раз в день через cron на сервере.

```cron
0 9 * * * cd /path/to/sub-tracker && docker compose exec -T web python manage.py check_trial_endings
```
