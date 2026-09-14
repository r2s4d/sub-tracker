"""Демо-данные для просмотра интерфейса и защиты проекта.

    python manage.py seed_demo            # создать пользователя demo, если его нет
    python manage.py seed_demo --reset    # удалить данные demo и создать заново

Создаёт подписки в разных категориях (чтобы круговая диаграмма не была пустой),
историю платежей за прошедшие месяцы (для линейного графика) и пробный период,
который скоро закончится (для напоминания).
"""

from datetime import date, timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.db import transaction

from subscriptions.models import (
    BillingPeriod, BillingType, Payment, PaymentMethod, Service, Subscription, Tag,
)
from subscriptions.services.billing import BillingCalculatorFactory
from subscriptions.services.dates import add_months

User = get_user_model()

DEMO_USERNAME = 'demo'
DEMO_PASSWORD = 'demo12345'


class Command(BaseCommand):
    help = 'Создаёт пользователя demo с подписками, платежами и тегами.'

    def add_arguments(self, parser):
        parser.add_argument('--reset', action='store_true', help='Пересоздать данные пользователя demo.')

    @transaction.atomic
    def handle(self, *args, reset=False, **options):
        user = User.objects.filter(username=DEMO_USERNAME).first()
        if user and not reset:
            self.stdout.write(f'Пользователь {DEMO_USERNAME} уже есть. Для пересоздания: --reset')
            return
        if user:
            user.delete()

        user = User.objects.create_user(DEMO_USERNAME, email='demo@example.com', password=DEMO_PASSWORD)
        today = date.today()

        card = PaymentMethod.objects.create(user=user, name='Т-Банк', kind=PaymentMethod.Kind.CARD, last4='4417')
        sber = PaymentMethod.objects.create(user=user, name='Сбер', kind=PaymentMethod.Kind.CARD, last4='0932')
        tags = {name: Tag.objects.create(user=user, name=name) for name in ('семья', 'работа', 'можно отменить')}

        def catalog(name):
            return Service.objects.get(name=name, owner=None)

        # (сервис, цена, тип, месяцев назад начата, карта, теги)
        plan = [
            ('Кинопоиск', '399', BillingType.MONTHLY, 14, card, ['семья']),
            ('Яндекс Музыка', '299', BillingType.MONTHLY, 20, card, []),
            ('МегаФон', '650', BillingType.MONTHLY, 30, sber, []),
            ('JetBrains', '8900', BillingType.YEARLY, 18, card, ['работа']),
            ('Timeweb Cloud', '590', BillingType.MONTHLY, 9, card, ['работа']),
            ('DDX Fitness', '2490', BillingType.MONTHLY, 5, sber, ['можно отменить']),
            ('iCloud+', '149', BillingType.MONTHLY, 11, card, ['семья']),
        ]
        for service_name, price, billing_type, months_ago, method, tag_names in plan:
            start = add_months(today, -months_ago)
            subscription = Subscription.objects.create(
                user=user, service=catalog(service_name), price=Decimal(price),
                billing_type=billing_type, start_date=start, payment_method=method,
            )
            subscription.tags.set([tags[name] for name in tag_names])
            # История платежей — по тем же датам, что считает калькулятор
            calculator = BillingCalculatorFactory.create(subscription)
            Payment.objects.bulk_create(
                Payment(subscription=subscription, amount=subscription.price, paid_at=paid_at, payment_method=method)
                for paid_at in calculator.charge_dates(start, today)
            )

        # Пробный период, который заканчивается через 2 дня — для напоминания
        trial = Subscription.objects.create(
            user=user, service=catalog('Claude Pro'), price=Decimal('2000'),
            billing_type=BillingType.TRIAL, start_date=today - timedelta(days=5),
            trial_end_date=today + timedelta(days=2),
            billing_period_after_trial=BillingPeriod.MONTHLY, payment_method=card,
        )
        trial.tags.set([tags['работа'], tags['можно отменить']])

        # Отключённая подписка: история платежей остаётся
        okko = Subscription.objects.create(
            user=user, service=catalog('Okko'), price=Decimal('349'), billing_type=BillingType.MONTHLY,
            start_date=add_months(today, -8), payment_method=sber, is_active=False,
        )
        Payment.objects.bulk_create(
            Payment(subscription=okko, amount=okko.price, paid_at=add_months(okko.start_date, i), payment_method=sber)
            for i in range(4)
        )

        self.stdout.write(self.style.SUCCESS(
            f'Готово: пользователь {DEMO_USERNAME} / пароль {DEMO_PASSWORD}. '
            f'Подписок: {user.subscriptions.count()}, '
            f'платежей: {Payment.objects.filter(subscription__user=user).count()}.'
        ))
