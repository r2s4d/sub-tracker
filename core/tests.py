"""Настройки для сервера: проверяются в отдельном процессе, потому что settings.py
читается один раз при старте, а здесь нужны разные переменные окружения."""

import os
import subprocess
import sys

from django.conf import settings
from django.test import SimpleTestCase

PRINT_SETTINGS = (
    'import django; django.setup(); from django.conf import settings as s; '
    'print(s.SESSION_COOKIE_SECURE, s.CSRF_COOKIE_SECURE, s.SECURE_SSL_REDIRECT, s.SECURE_HSTS_SECONDS)'
)


def run_with_env(**overrides):
    # Переменные окружения важнее .env: load_dotenv уже заданные не перезаписывает.
    env = {**os.environ, 'DJANGO_SETTINGS_MODULE': 'config.settings', **overrides}
    return subprocess.run(
        [sys.executable, '-c', PRINT_SETTINGS],
        cwd=settings.BASE_DIR, env=env, capture_output=True, text=True, timeout=60,
    )


class ProductionSettingsTests(SimpleTestCase):
    def test_server_refuses_to_start_without_secret_key(self):
        result = run_with_env(DJANGO_DEBUG='false', DJANGO_SECRET_KEY='')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('ImproperlyConfigured', result.stderr)

    def test_https_site_gets_secure_cookies_and_redirect(self):
        result = run_with_env(DJANGO_DEBUG='false', DJANGO_SECRET_KEY='test-key', SITE_URL='https://example.com')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.split(), ['True', 'True', 'True', '3600'])

    def test_http_site_keeps_plain_cookies(self):
        # Без HTTPS secure-cookie браузер не отправит, и войти на сайт будет нельзя.
        result = run_with_env(DJANGO_DEBUG='false', DJANGO_SECRET_KEY='test-key', SITE_URL='http://203.0.113.5')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.split(), ['False', 'False', 'False', '0'])
