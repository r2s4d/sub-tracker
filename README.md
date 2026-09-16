# Subscription Tracker

Веб-приложение для учёта личных подписок: стриминг, связь, хостинг, SaaS и т.д.
Показывает расходы по категориям, динамику по месяцам, ближайшие продления
и напоминает на почту об окончании пробного периода.

**Стек:** Django (server-side шаблоны) · PostgreSQL · Bootstrap · Chart.js · Docker

## Документация

- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md): слои, иерархия калькуляторов оплаты,
  стратегии уведомлений, изоляция пользователей, диаграммы классов
- [docs/DATABASE.md](docs/DATABASE.md): ER-диаграмма, ограничения целостности,
  справочные данные, авторизация и разделение данных

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

### HTTPS

Сертификат Let's Encrypt выпускается, когда сайт уже открывается по http,
а адрес из `SITE_URL` указывает на этот сервер:

```bash
docker compose -f docker-compose.yml -f docker-compose.https.yml run --rm \
  --entrypoint certbot certbot certonly --webroot -w /var/www/certbot \
  --cert-name site -d ВАШ.АДРЕС --agree-tos --register-unsafely-without-email
```

После этого в `.env` включается режим с HTTPS, и обычные команды `docker compose`
начинают учитывать оба файла:

```
COMPOSE_FILE=docker-compose.yml:docker-compose.https.yml
SITE_URL=https://ВАШ.АДРЕС
```

`docker compose up -d` поднимет nginx с сертификатом, перенаправлением с http
и контейнер `certbot`, который продлевает сертификат.

Напоминания об окончании триала: раз в день, например systemd-таймером
или строкой cron, если он установлен.

```cron
0 9 * * * cd /path/to/sub-tracker && docker compose exec -T web python manage.py check_trial_endings
```
