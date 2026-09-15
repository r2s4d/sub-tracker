"""Уведомления: поиск напоминаний и стратегии доставки (DashboardNotifier, EmailNotifier)."""

from datetime import date
from decimal import Decimal
from io import StringIO
from unittest import mock

from django.core import mail
from django.core.management import call_command
from django.test import TestCase, override_settings

from subscriptions.models import BillingPeriod, NotificationLog, PaymentMethod, Service
from subscriptions.services.notifications import (
    DashboardNotifier,
    EmailNotifier,
    collect_reminders,
    days_left_phrase,
)

from .utils import make_category, make_subscription, make_trial, make_user

TODAY = date(2026, 9, 14)
LOCMEM = override_settings(
    EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend',
    SITE_URL='https://subs.example',
    DEFAULT_FROM_EMAIL='noreply@subs.example',
)


class NotificationDataMixin:
    def setUp(self):
        self.user = make_user('anna')
        self.other = make_user('boris')
        category = make_category('notify')
        self.service = Service.objects.create(name='test-Кино', category=category)
        self.trial_service = Service.objects.create(name='test-ИИ-помощник', category=category)
        self.card = PaymentMethod.objects.create(user=self.user, name='test-Банк', last4='1234')

        # Ежемесячная: следующее списание 20.09 (через 6 дней)
        self.monthly = make_subscription(self.user, self.service, start_date=date(2026, 1, 20))
        # Триал: заканчивается 16.09 (через 2 дня), потом 2000 ₽ в месяц
        self.trial = make_trial(
            self.user, self.trial_service, price=Decimal('2000.00'), start_date=date(2026, 9, 9),
            trial_end_date=date(2026, 9, 16), payment_method=self.card,
        )


class CollectRemindersTests(NotificationDataMixin, TestCase):
    def test_trial_end_and_renewal_kinds(self):
        """Конец триала - TRIAL_ENDING, обычное продление - RENEWAL_UPCOMING."""
        reminders = collect_reminders(self.user, TODAY, horizon_days=30)
        kinds = {r.subscription.pk: r.kind for r in reminders}
        self.assertEqual(kinds[self.trial.pk], NotificationLog.Kind.TRIAL_ENDING)
        self.assertEqual(kinds[self.monthly.pk], NotificationLog.Kind.RENEWAL_UPCOMING)

    def test_sorted_by_date_with_days_left(self):
        """Напоминания отсортированы по дате, days_left считается от today."""
        reminders = collect_reminders(self.user, TODAY, horizon_days=30)
        self.assertEqual([r.event_date for r in reminders], [date(2026, 9, 16), date(2026, 9, 20)])
        self.assertEqual([r.days_left for r in reminders], [2, 6])

    def test_horizon_limits_results(self):
        """События дальше горизонта не попадают в список."""
        reminders = collect_reminders(self.user, TODAY, horizon_days=3)
        self.assertEqual([r.subscription for r in reminders], [self.trial])

    def test_inactive_excluded(self):
        """Отключённые подписки не напоминают о себе."""
        self.monthly.is_active = False
        self.monthly.save()
        reminders = collect_reminders(self.user, TODAY, horizon_days=30)
        self.assertNotIn(self.monthly, [r.subscription for r in reminders])

    def test_after_trial_end_it_is_a_regular_renewal(self):
        """Когда триал закончился, следующее списание - обычное продление."""
        reminders = collect_reminders(self.user, date(2026, 9, 17), horizon_days=40)
        trial_reminder = next(r for r in reminders if r.subscription == self.trial)
        self.assertEqual(trial_reminder.kind, NotificationLog.Kind.RENEWAL_UPCOMING)
        self.assertEqual(trial_reminder.event_date, date(2026, 10, 16))

    def test_other_users_subscriptions_never_included(self):
        """В напоминания попадают только подписки этого пользователя."""
        make_subscription(self.other, self.service, start_date=date(2026, 1, 15))
        reminders = collect_reminders(self.user, TODAY, horizon_days=30)
        self.assertTrue(all(r.subscription.user_id == self.user.pk for r in reminders))


class DashboardNotifierTests(NotificationDataMixin, TestCase):
    def test_returns_all_or_limited(self):
        reminders = collect_reminders(self.user, TODAY)
        self.assertEqual(DashboardNotifier().deliver(self.user, reminders), reminders)
        self.assertEqual(DashboardNotifier(limit=1).deliver(self.user, reminders), reminders[:1])

    def test_has_no_side_effects(self):
        """Дашборд не пишет журнал и не шлёт писем - только показывает."""
        DashboardNotifier().deliver(self.user, collect_reminders(self.user, TODAY))
        self.assertFalse(NotificationLog.objects.exists())
        self.assertEqual(len(mail.outbox), 0)


@LOCMEM
class EmailNotifierTests(NotificationDataMixin, TestCase):
    def deliver(self, today=TODAY):
        return EmailNotifier().deliver(self.user, collect_reminders(self.user, today, horizon_days=30))

    def test_sends_only_trial_endings(self):
        """Письмо только про окончание триала, обычные продления не отправляются."""
        delivered = self.deliver()
        self.assertEqual([r.subscription for r in delivered], [self.trial])
        self.assertEqual(len(mail.outbox), 1)
        self.assertNotIn('test-Кино', mail.outbox[0].body)

    def test_message_content(self):
        """В письме: название, когда кончается, сумма, периодичность, карта и ссылка."""
        self.deliver()
        message = mail.outbox[0]
        self.assertEqual(message.to, ['anna@example.com'])
        self.assertIn('test-ИИ-помощник', message.subject)
        self.assertIn('через 2 дня', message.body)
        self.assertIn('16 сентября', message.body)
        self.assertIn('2 000,00 ₽ в месяц', message.body)
        self.assertIn('test-Банк *1234', message.body)
        self.assertIn(f'https://subs.example/subscriptions/{self.trial.pk}/', message.body)
        self.assertEqual(message.alternatives[0][1], 'text/html')

    def test_one_email_per_user_for_several_trials(self):
        """Несколько триалов одного пользователя - одно письмо со всеми."""
        second = make_trial(self.user, self.service, start_date=date(2026, 9, 1), trial_end_date=date(2026, 9, 15))
        delivered = self.deliver()
        self.assertEqual({r.subscription for r in delivered}, {self.trial, second})
        self.assertEqual(len(mail.outbox), 1)

    def test_respects_notify_days_before(self):
        """Не пишет раньше, чем пользователь попросил в настройках."""
        profile = self.user.profile
        profile.notify_days_before = 1
        profile.save()
        self.assertEqual(self.deliver(), [])
        self.assertEqual(self.deliver(today=date(2026, 9, 15))[0].subscription, self.trial)

    def test_second_run_sends_nothing(self):
        """Повторный запуск в тот же или следующий день не дублирует письмо."""
        self.deliver()
        self.deliver()
        self.deliver(today=date(2026, 9, 15))
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(NotificationLog.objects.filter(channel=NotificationLog.Channel.EMAIL).count(), 1)

    def test_prefers_notification_email(self):
        profile = self.user.profile
        profile.notification_email = 'work@example.com'
        profile.save()
        self.deliver()
        self.assertEqual(mail.outbox[0].to, ['work@example.com'])

    def test_no_address_no_email(self):
        """Без почты письмо не отправляется и в журнал ничего не пишется - можно добавить почту позже."""
        self.user.email = ''
        self.user.save()
        self.assertEqual(self.deliver(), [])
        self.assertFalse(NotificationLog.objects.exists())

    def test_failed_sending_leaves_no_log(self):
        """Если SMTP упал, журнал откатывается - следующий запуск попробует снова."""
        with mock.patch('django.core.mail.EmailMultiAlternatives.send', side_effect=OSError('smtp down')):
            with self.assertRaises(OSError):
                self.deliver()
        self.assertFalse(NotificationLog.objects.exists())
        self.deliver()
        self.assertEqual(len(mail.outbox), 1)

    def test_days_left_phrase(self):
        cases = {0: 'сегодня', 1: 'завтра', 2: 'через 2 дня', 5: 'через 5 дней', 21: 'через 21 день', 12: 'через 12 дней'}
        for days, phrase in cases.items():
            with self.subTest(days=days):
                self.assertEqual(days_left_phrase(days), phrase)


@LOCMEM
class CheckTrialEndingsCommandTests(NotificationDataMixin, TestCase):
    def run_command(self, *args, **kwargs):
        out = StringIO()
        call_command('check_trial_endings', *args, stdout=out, **kwargs)
        return out.getvalue()

    def test_sends_and_logs(self):
        output = self.run_command(date='2026-09-14')
        self.assertEqual(len(mail.outbox), 1)
        self.assertTrue(NotificationLog.objects.filter(subscription=self.trial).exists())
        self.assertIn('писем отправлено: 1', output)

    def test_dry_run_sends_and_logs_nothing(self):
        output = self.run_command('--dry-run', date='2026-09-14')
        self.assertEqual(len(mail.outbox), 0)
        self.assertFalse(NotificationLog.objects.exists())
        self.assertIn('test-ИИ-помощник', output)

    def test_running_twice_sends_once(self):
        self.run_command(date='2026-09-14')
        output = self.run_command(date='2026-09-14')
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn('пропущено как уже отправленные: 1', output)

    def test_users_without_trials_are_not_emailed(self):
        """Пользователь только с обычными подписками в рассылку не попадает."""
        make_subscription(self.other, self.service, start_date=date(2026, 1, 15))
        self.run_command(date='2026-09-14')
        self.assertEqual([m.to for m in mail.outbox], [['anna@example.com']])

    def test_trial_far_in_future_is_not_emailed_yet(self):
        self.run_command(date='2026-09-01')
        self.assertEqual(len(mail.outbox), 0)

    def test_invalid_date(self):
        from django.core.management.base import CommandError
        with self.assertRaises(CommandError):
            self.run_command(date='14.09.2026')
