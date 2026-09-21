# Мониторинг сайта SUb-Tracker

Стек для лабораторной работы №1: Prometheus + Blackbox exporter + Grafana в Docker Compose.
Работает на том же VPS, что и сайт, но в отдельном compose-проекте `monitoring`
(свои контейнеры, сеть и тома, приложение `subtracker` не затрагивается).

```
Blackbox ──> https://151-243-224-253.sslip.io/accounts/login/   (как посетитель, снаружи)
   ▲
   │ каждые 15 с
Prometheus ──> Grafana (дашборд «Мониторинг сайта SUb-Tracker»)
```

| Компонент | Образ | Порт | Память |
|---|---|---|---|
| Blackbox exporter | `prom/blackbox-exporter:v0.28.0` | не публикуется | 64 МБ |
| Prometheus | `prom/prometheus:v3.14.0` | `127.0.0.1:9090` | 256 МБ |
| Grafana | `grafana/grafana:13.2.2` | `127.0.0.1:3000` | 256 МБ |

Что измеряется: доступность (`probe_success`), время отклика (`probe_duration_seconds`),
HTTP-код (`probe_http_status_code`), срок сертификата (`probe_ssl_earliest_cert_expiry`).

## Поднять

На сервере, в клоне репозитория:

```bash
cd monitoring
cp .env.example .env
chmod 600 .env
# заполнить GRAFANA_ADMIN_USER и GRAFANA_ADMIN_PASSWORD (пароль: openssl rand -base64 24)
docker compose up -d
```

Источник данных и дашборд создаются сами (provisioning, файлы в `grafana/`),
ничего настраивать в интерфейсе не нужно.

## Остановить и перезапустить

```bash
docker compose restart          # перезапуск, данные и дашборд сохраняются
docker compose stop             # остановить, ничего не удаляя
docker compose down             # убрать контейнеры, тома с данными остаются
```

Не используйте `down -v`: он удалит тома `prometheus_data` и `grafana_data`.

## Зайти через SSH-туннель

Порты слушают только loopback сервера, из интернета их не видно. С ноутбука:

```bash
ssh -N -L 3000:127.0.0.1:3000 -L 9090:127.0.0.1:9090 user@151.243.224.253
```

Пока команда работает (окно занято, так и задумано):

- Grafana: http://localhost:3000
- Prometheus: http://localhost:9090

## Где пароль

Логин и пароль Grafana лежат только в `monitoring/.env` на сервере (права 600).
В git попадает лишь `.env.example`. Прочитать пароль на сервере:

```bash
grep GRAFANA_ADMIN monitoring/.env
```

Регистрация в Grafana и анонимный доступ выключены.

## Как устроено

- `docker-compose.yml`: три сервиса, лимиты памяти, данные в named volume.
- `prometheus.yml`: интервал сбора 15 с, задание `blackbox` с адресом сайта.
- `blackbox.yml`: модуль `http_2xx`, ходит по HTTPS, проверяет сертификат, таймаут 5 с.
- `grafana/provisioning/`: источник данных Prometheus и подключение папки с дашбордами.
- `grafana/dashboards/site.json`: сам дашборд.

## Ограничение

Мониторинг стоит на том же сервере, что и сайт. Если упадёт весь сервер, упадёт и
мониторинг, и никто этого не заметит. Для такого случая нужна внешняя проверка
(UptimeRobot).
