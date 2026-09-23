"""Общая обвязка UI-тестов.

Тесты работают с настоящим браузером (Chromium через Playwright) и настоящим
сервером: pytest-django поднимает приложение на localhost вместе с тестовой
базой, браузер ходит на него как обычный посетитель.

Данные создаются заново в каждом тесте через ORM, поэтому тесты не зависят
друг от друга и от порядка запуска. Справочники (категории и сервисы) тоже
создаются здесь, а не берутся из миграции: живой сервер работает в отдельном
потоке, и между тестами база очищается полностью.
"""

import os
from datetime import date, timedelta
from decimal import Decimal

# Playwright работает через цикл событий, и Django считает обращение к базе из него
# опасным. В тестах это безопасно: запросы идут последовательно, поэтому снимаем запрет.
os.environ.setdefault('DJANGO_ALLOW_ASYNC_UNSAFE', 'true')

import allure  # noqa: E402
import pytest  # noqa: E402
from django.contrib.auth.models import User  # noqa: E402

from subscriptions.models import (  # noqa: E402
    BillingType, Category, Payment, PaymentMethod, Service, Subscription, Tag,
)

PASSWORD = 'ui-test-password-123'


@pytest.fixture(autouse=True)
def browser_window(page):
    """Одинаковое окно во всех тестах: обзор рассчитан на широкий экран."""
    page.set_viewport_size({'width': 1440, 'height': 900})
    page.set_default_timeout(10_000)
    return page


def make_service(name, category_name, slug, color, sort_order):
    """Ищет категорию и сервис по названию, создаёт, если их нет.

    Поиск именно по названию: справочник мог прийти из миграции со своими кодами,
    а после очистки базы между тестами его может не быть вовсе. В обоих случаях
    тест получает рабочие данные.
    """
    category, _ = Category.objects.get_or_create(
        name=category_name,
        defaults={'slug': slug, 'color': color, 'sort_order': sort_order},
    )
    service, _ = Service.objects.get_or_create(name=name, owner=None, defaults={'category': category})
    return service


@pytest.fixture
def catalog(transactional_db):
    """Минимальный каталог сервисов для форм и фильтров: три категории, три сервиса."""
    return {
        'Кинопоиск': make_service('Кинопоиск', 'Развлечения', 'ui-entertainment', '#8F3B76', 1),
        'JetBrains': make_service('JetBrains', 'Работа', 'ui-work', '#2D6E7E', 2),
        'МегаФон': make_service('МегаФон', 'Связь', 'ui-mobile', '#9C6B1F', 3),
    }


@pytest.fixture
def user(catalog):
    """Пользователь с подписками, платежом и тегом: на нём проверяется интерфейс."""
    owner = User.objects.create_user('tester', email='tester@example.com', password=PASSWORD)
    today = date.today()
    card = PaymentMethod.objects.create(user=owner, name='Т-Банк', kind=PaymentMethod.Kind.CARD, last4='4417')
    tag = Tag.objects.create(user=owner, name='семья')

    kinopoisk = Subscription.objects.create(
        user=owner, service=catalog['Кинопоиск'], price=Decimal('399'),
        billing_type=BillingType.MONTHLY, start_date=today - timedelta(days=90),
        payment_method=card,
    )
    kinopoisk.tags.set([tag])
    Payment.objects.create(subscription=kinopoisk, amount=Decimal('399'), paid_at=today - timedelta(days=30))

    Subscription.objects.create(
        user=owner, service=catalog['JetBrains'], price=Decimal('8900'),
        billing_type=BillingType.YEARLY, start_date=today - timedelta(days=200),
        payment_method=card,
    )
    Subscription.objects.create(
        user=owner, service=catalog['МегаФон'], price=Decimal('650'),
        billing_type=BillingType.MONTHLY, start_date=today - timedelta(days=45),
        payment_method=card,
    )
    return owner


@pytest.fixture
def other_user(catalog):
    """Второй пользователь: нужен, чтобы проверить, что чужие данные недоступны."""
    stranger = User.objects.create_user('stranger', email='stranger@example.com', password=PASSWORD)
    subscription = Subscription.objects.create(
        user=stranger, service=catalog['Кинопоиск'], price=Decimal('299'),
        billing_type=BillingType.MONTHLY, start_date=date.today() - timedelta(days=10),
    )
    return stranger, subscription


@pytest.fixture
def login(page, live_server):
    """Вход через настоящую форму, а не подстановкой cookie: путь такой же, как у человека."""

    def _login(username='tester', password=PASSWORD):
        with allure.step(f'Войти в аккаунт «{username}» через форму входа'):
            page.goto(f'{live_server.url}/accounts/login/')
            page.fill('#id_username', username)
            page.fill('#id_password', password)
            page.click('button[type="submit"]')
            page.wait_for_load_state('networkidle')

    return _login


@pytest.hookimpl(hookwrapper=True, tryfirst=True)
def pytest_runtest_makereport(item, call):
    """Скриншот страницы прикладывается к отчёту Allure, когда тест упал."""
    outcome = yield
    report = outcome.get_result()
    if report.when == 'call' and report.failed:
        page = item.funcargs.get('page')
        if page is not None:
            allure.attach(
                page.screenshot(full_page=True),
                name='Экран в момент падения',
                attachment_type=allure.attachment_type.PNG,
            )
            allure.attach(page.url, name='Адрес страницы', attachment_type=allure.attachment_type.TEXT)
