"""Общие помощники для тестов views.

Категории и сервисы создаются свои, с префиксом test-: тесты не зависят
от data-миграции 0002 с каталогом, но и не конфликтуют с ней по названиям.
"""

from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.urls import reverse

from subscriptions.models import (
    BillingPeriod,
    BillingType,
    Category,
    Payment,
    PaymentMethod,
    Service,
    Subscription,
    Tag,
)

User = get_user_model()
PASSWORD = 'pass12345'


def make_user(username):
    return User.objects.create_user(username, email=f'{username}@example.com', password=PASSWORD)


def make_category(suffix='main', sort_order=0):
    return Category.objects.create(
        name=f'test-Категория-{suffix}',
        slug=f'test-category-{suffix}',
        color='#4F46E5',
        sort_order=sort_order,
    )


def make_subscription(user, service, **kwargs):
    data = {
        'user': user,
        'service': service,
        'price': Decimal('299.00'),
        'billing_type': BillingType.MONTHLY,
        'start_date': date(2026, 1, 1),
    }
    data.update(kwargs)
    return Subscription.objects.create(**data)


def make_trial(user, service, **kwargs):
    data = {
        'billing_type': BillingType.TRIAL,
        'trial_end_date': date(2026, 1, 15),
        'billing_period_after_trial': BillingPeriod.MONTHLY,
    }
    data.update(kwargs)
    return make_subscription(user, service, **data)


def subscription_post_data(service, **overrides):
    """Валидные POST-данные формы подписки (ежемесячная)."""
    data = {
        'service': service.pk,
        'title': '',
        'price': '499.00',
        'billing_type': BillingType.MONTHLY,
        'start_date': '2026-02-01',
        'trial_end_date': '',
        'billing_period_after_trial': '',
        'payment_method': '',
        'is_active': 'on',
        'notes': '',
    }
    data.update(overrides)
    return {key: value for key, value in data.items() if value is not None}


def login_redirect_url(url):
    return f"{reverse('login')}?next={url}"


__all__ = [
    'BillingPeriod', 'BillingType', 'Category', 'Payment', 'PaymentMethod', 'Service',
    'Subscription', 'Tag', 'User', 'make_user', 'make_category', 'make_subscription',
    'make_trial', 'subscription_post_data', 'login_redirect_url',
]
