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
