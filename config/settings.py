"""
Django settings for the Subscription Tracker project.

Все секреты и параметры окружения читаются из переменных окружения
(локально - из файла .env, который не коммитится; шаблон - .env.example).
"""

import os
from pathlib import Path

from django.core.exceptions import ImproperlyConfigured
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent

load_dotenv(BASE_DIR / '.env')


def env_bool(name, default=False):
    return os.environ.get(name, str(default)).lower() in ('1', 'true', 'yes', 'on')


def env_list(name, default=''):
    return [item.strip() for item in os.environ.get(name, default).split(',') if item.strip()]


DEBUG = env_bool('DJANGO_DEBUG', False)

SECRET_KEY = os.environ.get('DJANGO_SECRET_KEY', '')
if not SECRET_KEY:
    if not DEBUG:
        # На сервере без ключа не стартуем: ключ по умолчанию лежит в открытом репозитории,
        # и с ним можно подделать cookie сессии.
        raise ImproperlyConfigured('Задайте DJANGO_SECRET_KEY в .env')
    SECRET_KEY = 'dev-insecure-key-change-me'

ALLOWED_HOSTS = env_list('DJANGO_ALLOWED_HOSTS', 'localhost,127.0.0.1')

# Адрес сайта для ссылок в письмах (команда из cron не знает домен запроса)
SITE_URL = os.environ.get('SITE_URL', 'http://localhost:8000')


INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',

    'core',
    'accounts',
    'subscriptions',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'config.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'templates'],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'config.wsgi.application'


# PostgreSQL с самого начала (ТЗ, раздел 1)
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.postgresql',
        'NAME': os.environ.get('POSTGRES_DB', 'subtracker'),
        'USER': os.environ.get('POSTGRES_USER', 'subtracker'),
        'PASSWORD': os.environ.get('POSTGRES_PASSWORD', ''),
        'HOST': os.environ.get('POSTGRES_HOST', 'localhost'),
        'PORT': os.environ.get('POSTGRES_PORT', '5432'),
    }
}


AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]


LANGUAGE_CODE = 'ru-ru'

TIME_ZONE = 'Europe/Moscow'

USE_I18N = True

USE_TZ = True


STATIC_URL = 'static/'
STATICFILES_DIRS = [BASE_DIR / 'static']
STATIC_ROOT = BASE_DIR / 'staticfiles'

LOGIN_URL = 'login'
LOGIN_REDIRECT_URL = 'home'
LOGOUT_REDIRECT_URL = 'login'

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'


# Почта: SMTP Яндекса. Без настроек письма печатаются в консоль.
EMAIL_BACKEND = os.environ.get('EMAIL_BACKEND', 'django.core.mail.backends.console.EmailBackend')
EMAIL_HOST = os.environ.get('EMAIL_HOST', 'smtp.yandex.ru')
EMAIL_PORT = int(os.environ.get('EMAIL_PORT', '465'))
EMAIL_USE_SSL = env_bool('EMAIL_USE_SSL', True)
EMAIL_USE_TLS = env_bool('EMAIL_USE_TLS', False)
EMAIL_HOST_USER = os.environ.get('EMAIL_HOST_USER', '')
EMAIL_HOST_PASSWORD = os.environ.get('EMAIL_HOST_PASSWORD', '')
DEFAULT_FROM_EMAIL = (
    os.environ.get('DEFAULT_FROM_EMAIL')
    or EMAIL_HOST_USER
    or 'Subscription Tracker <noreply@localhost>'
)


# Работа за nginx. Django видит запрос от nginx по http, поэтому о настоящем протоколе
# узнаёт из заголовка X-Forwarded-Proto (nginx его всегда перезаписывает, клиент подменить не может).
SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')

# Форма входа отправляется POST-запросом, и Django сверяет Origin с этим списком (защита от CSRF).
CSRF_TRUSTED_ORIGINS = env_list('DJANGO_CSRF_TRUSTED_ORIGINS', SITE_URL)

# Когда сайт работает по HTTPS, cookie сессии и CSRF не уходят по незашифрованному http.
HTTPS_ENABLED = SITE_URL.startswith('https://')
SESSION_COOKIE_SECURE = HTTPS_ENABLED
CSRF_COOKIE_SECURE = HTTPS_ENABLED
if HTTPS_ENABLED:
    SECURE_SSL_REDIRECT = True
    # Сначала на час: если с сертификатом что-то не так, браузеры быстро забудут правило.
    SECURE_HSTS_SECONDS = int(os.environ.get('DJANGO_HSTS_SECONDS', '3600'))

SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = 'same-origin'

# Логи в stdout: на сервере их показывает `docker compose logs web`.
LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'handlers': {'console': {'class': 'logging.StreamHandler'}},
    'root': {'handlers': ['console'], 'level': 'WARNING'},
}
