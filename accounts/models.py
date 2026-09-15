from django.conf import settings
from django.db import models


class UserProfile(models.Model):
    """Настройки пользователя, которых нет во встроенной модели User.

    Отдельная таблица со связью 1:1, а не кастомный User: встроенный auth
    остаётся нетронутым, а профиль расширяет его только нужными полями.
    """

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='profile',
        verbose_name='пользователь',
    )
    notification_email = models.EmailField(
        'почта для уведомлений',
        blank=True,
        help_text='Если не указана, используется почта аккаунта.',
    )
    notify_days_before = models.PositiveSmallIntegerField(
        'предупреждать за, дней',
        default=3,
    )
    monthly_budget = models.DecimalField(
        'месячный бюджет, ₽',
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
    )

    class Meta:
        verbose_name = 'профиль'
        verbose_name_plural = 'профили'

    def __str__(self):
        return f'Профиль {self.user}'

    @property
    def effective_email(self):
        return self.notification_email or self.user.email
