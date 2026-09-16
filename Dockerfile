# Образ приложения: Django + gunicorn. Статику раздаёт nginx (см. docker-compose.yml).
FROM python:3.12-slim

# Не писать .pyc и не буферизовать вывод: логи сразу видны в `docker compose logs`.
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Зависимости отдельным слоем: при правке кода они не переустанавливаются.
COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . .

# Приложение работает не от root: при уязвимости в коде у процесса меньше прав.
RUN useradd --system --create-home app \
    && mkdir -p /app/staticfiles \
    && chown app /app/staticfiles \
    && chmod +x docker/entrypoint.sh
USER app

EXPOSE 8000

ENTRYPOINT ["docker/entrypoint.sh"]
CMD ["gunicorn", "config.wsgi:application", "--bind", "0.0.0.0:8000", "--workers", "3", "--access-logfile", "-"]
