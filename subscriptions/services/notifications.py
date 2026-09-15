"""Уведомления о ближайших списаниях — паттерн «Стратегия».

    NotificationStrategy (интерфейс)
    ├── DashboardNotifier  — показывает напоминания на дашборде (без побочных эффектов)
    └── EmailNotifier      — отправляет письмо об окончании пробного периода

Сначала collect_reminders() один раз находит события (что и когда спишется),
затем стратегия решает, КАК о них сообщить. Код, который вызывает
notifier.deliver(user, reminders), не знает, куда уйдёт уведомление:
стратегию можно подменить, не меняя поиск событий.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.db import transaction
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils import timezone, translation

from subscriptions.models import BillingType, NotificationLog, Subscription

from .billing import BillingCalculatorFactory


@dataclass(frozen=True)
class Reminder:
    subscription: Subscription
    kind: str  # NotificationLog.Kind
    event_date: date
    days_left: int
    amount: Decimal

    @property
    def is_trial_ending(self) -> bool:
        return self.kind == NotificationLog.Kind.TRIAL_ENDING


def collect_reminders(user, today: date | None = None, horizon_days: int = 30) -> list[Reminder]:
    """Ближайшие списания активных подписок пользователя в пределах horizon_days.

    Для подписки на пробном периоде событие — окончание триала (первое списание),
    для остальных — очередное продление.
    """
    today = today or timezone.localdate()
    horizon = today + timedelta(days=horizon_days)
    subscriptions = (
        Subscription.objects.filter(user=user, is_active=True)
        .select_related('service__category', 'payment_method')
    )
    reminders = []
    for subscription in subscriptions:
        calculator = BillingCalculatorFactory.create(subscription)
        next_date = calculator.calculate_next_renewal(today)
        if next_date > horizon:
            continue
        is_trial_end = subscription.billing_type == BillingType.TRIAL and next_date == subscription.trial_end_date
        reminders.append(Reminder(
            subscription=subscription,
            kind=NotificationLog.Kind.TRIAL_ENDING if is_trial_end else NotificationLog.Kind.RENEWAL_UPCOMING,
            event_date=next_date,
            days_left=(next_date - today).days,
            amount=subscription.price,
        ))
    return sorted(reminders, key=lambda r: (r.event_date, r.subscription.service.name))


class NotificationStrategy(ABC):
    """Интерфейс стратегии: как доставить пользователю найденные напоминания."""

    channel: str  # NotificationLog.Channel

    @abstractmethod
    def deliver(self, user, reminders: list[Reminder]) -> list[Reminder]:
        """Доставляет напоминания и возвращает те, о которых действительно сообщено."""


class DashboardNotifier(NotificationStrategy):
    """Напоминания для дашборда: всё в пределах горизонта, ничего не пишет в БД.

    Дашборд перерисовывается при каждом заходе, поэтому журнал не нужен —
    показываем актуальный список каждый раз.
    """

    channel = NotificationLog.Channel.DASHBOARD

    def __init__(self, limit: int | None = None):
        self.limit = limit

    def deliver(self, user, reminders: list[Reminder]) -> list[Reminder]:
        return reminders[:self.limit] if self.limit else list(reminders)


def days_left_phrase(days: int) -> str:
    """0 → «сегодня», 1 → «завтра», 2 → «через 2 дня», 5 → «через 5 дней»."""
    if days <= 0:
        return 'сегодня'
    if days == 1:
        return 'завтра'
    if days % 10 == 1 and days % 100 != 11:
        word = 'день'
    elif 2 <= days % 10 <= 4 and not 12 <= days % 100 <= 14:
        word = 'дня'
    else:
        word = 'дней'
    return f'через {days} {word}'


def charge_period_phrase(subscription: Subscription) -> str:
    """«в месяц» / «в год» — по калькулятору, который будет списывать деньги после триала."""
    calculator = BillingCalculatorFactory.create(subscription)
    periodic = getattr(calculator, 'after_trial', calculator)
    return 'в год' if getattr(periodic, 'period_months', 1) == 12 else 'в месяц'


class EmailNotifier(NotificationStrategy):
    """Письмо об окончании пробного периода — одно на пользователя.

    Обычные продления сюда не попадают: их показывает дашборд, а письмо нужно
    там, где деньги спишутся неожиданно — после бесплатного периода (ТЗ, этап 3).
    """

    channel = NotificationLog.Channel.EMAIL

    subject_template = 'emails/trial_ending_subject.txt'
    text_template = 'emails/trial_ending.txt'
    html_template = 'emails/trial_ending.html'

    def select(self, user, reminders: list[Reminder]) -> list[Reminder]:
        """Окончания триала в пределах «предупреждать за N дней» из профиля."""
        days_before = user.profile.notify_days_before
        return [r for r in reminders if r.is_trial_ending and 0 <= r.days_left <= days_before]

    def pending(self, user, reminders: list[Reminder]) -> list[Reminder]:
        """То, что было бы отправлено сейчас: подходящее и ещё не записанное в журнал."""
        return [r for r in self.select(user, reminders) if not self._already_logged(r)]

    def deliver(self, user, reminders: list[Reminder]) -> list[Reminder]:
        recipient = user.profile.effective_email
        candidates = self.pending(user, reminders)
        if not recipient or not candidates:
            return []

        # Запись в журнал и отправка — в одной транзакции. get_or_create опирается
        # на уникальный индекс NotificationLog: параллельный запуск упрётся в него
        # и получит created=False, так что письмо не уйдёт дважды. Если SMTP
        # упадёт, исключение откатит транзакцию вместе с записями журнала —
        # и следующий запуск cron попробует снова, а не «забудет» напоминание.
        with transaction.atomic():
            fresh = []
            for reminder in candidates:
                _, created = NotificationLog.objects.get_or_create(
                    subscription=reminder.subscription,
                    kind=reminder.kind,
                    channel=self.channel,
                    event_date=reminder.event_date,
                )
                if created:
                    fresh.append(reminder)
            if fresh:
                self.build_message(user, recipient, fresh).send()
        return fresh

    def _already_logged(self, reminder: Reminder) -> bool:
        return NotificationLog.objects.filter(
            subscription=reminder.subscription,
            kind=reminder.kind,
            channel=self.channel,
            event_date=reminder.event_date,
        ).exists()

    def build_message(self, user, recipient: str, reminders: list[Reminder]) -> EmailMultiAlternatives:
        site_url = settings.SITE_URL.rstrip('/')
        items = [
            {
                'name': r.subscription.display_name,
                'when': days_left_phrase(r.days_left),
                'date': r.event_date,
                'amount': r.amount,
                'period': charge_period_phrase(r.subscription),
                'payment_method': r.subscription.payment_method,
                'url': site_url + reverse('subscriptions:detail', args=[r.subscription.pk]),
            }
            for r in reminders
        ]
        context = {'user': user, 'items': items, 'site_url': site_url}
        # Команда запускается из cron, где язык запроса не выбран: даты («16 сентября»)
        # должны выйти по-русски независимо от окружения.
        with translation.override(settings.LANGUAGE_CODE):
            subject = ' '.join(render_to_string(self.subject_template, context).split())
            text = render_to_string(self.text_template, context)
            html = render_to_string(self.html_template, context)
        message = EmailMultiAlternatives(subject, text, settings.DEFAULT_FROM_EMAIL, [recipient])
        message.attach_alternative(html, 'text/html')
        return message
