"""Письма об окончании пробных периодов. Запускается cron раз в день.

    python manage.py check_trial_endings                    # отправить
    python manage.py check_trial_endings --dry-run          # показать, что было бы отправлено
    python manage.py check_trial_endings --date 2026-09-14  # «притвориться», что сегодня эта дата

Строка crontab на VPS (каждый день в 9:00):
    0 9 * * * cd /app && python manage.py check_trial_endings
или, если проект запущен в Docker:
    0 9 * * * cd /opt/sub-tracker && docker compose exec -T web python manage.py check_trial_endings

Celery здесь не нужен: одна задача раз в сутки, повторная отправка исключена
журналом NotificationLog, так что достаточно cron.
"""

from datetime import date, timedelta

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from subscriptions.models import BillingType
from subscriptions.services.notifications import EmailNotifier, collect_reminders

User = get_user_model()

# Верхняя граница поиска: дальше этого срока никто не просит предупреждать.
MAX_NOTIFY_DAYS = 60


class Command(BaseCommand):
    help = 'Отправляет письма пользователям, у которых скоро заканчивается пробный период.'

    def add_arguments(self, parser):
        parser.add_argument('--date', help='Дата «сегодня» в формате ГГГГ-ММ-ДД (для проверки).')
        parser.add_argument('--dry-run', action='store_true', help='Ничего не отправлять, только показать.')

    def handle(self, *args, date=None, dry_run=False, **options):
        today = self._parse_date(date) if date else timezone.localdate()
        notifier = EmailNotifier()

        # Только пользователи, у которых вообще есть активный триал в ближайшие 60 дней —
        # не перебираем всех пользователей базы.
        users = (
            User.objects.filter(
                subscriptions__is_active=True,
                subscriptions__billing_type=BillingType.TRIAL,
                subscriptions__trial_end_date__range=(today, today + timedelta(days=MAX_NOTIFY_DAYS)),
            )
            .select_related('profile')
            .distinct()
        )

        checked = sent_emails = sent_reminders = skipped = 0
        for user in users:
            checked += 1
            reminders = collect_reminders(user, today, horizon_days=user.profile.notify_days_before)
            selected = notifier.select(user, reminders)
            pending = notifier.pending(user, reminders)
            skipped += len(selected) - len(pending)

            if dry_run:
                if pending:
                    names = ', '.join(r.subscription.display_name for r in pending)
                    self.stdout.write(f'{user.username} <{user.profile.effective_email or "нет почты"}>: {names}')
                continue

            delivered = notifier.deliver(user, reminders)
            if delivered:
                sent_emails += 1
                sent_reminders += len(delivered)

        prefix = 'Проверка без отправки. ' if dry_run else ''
        self.stdout.write(self.style.SUCCESS(
            f'{prefix}Дата: {today:%d.%m.%Y}. Пользователей проверено: {checked}, '
            f'писем отправлено: {sent_emails} (напоминаний: {sent_reminders}), '
            f'пропущено как уже отправленные: {skipped}.'
        ))

    @staticmethod
    def _parse_date(value: str) -> date:
        try:
            return date.fromisoformat(value)
        except ValueError:
            raise CommandError('Дата должна быть в формате ГГГГ-ММ-ДД, например 2026-09-14.') from None
