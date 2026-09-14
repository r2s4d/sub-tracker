from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models
from django.db.models import Q


class BillingType(models.TextChoices):
    MONTHLY = 'monthly', 'Ежемесячно'
    YEARLY = 'yearly', 'Ежегодно'
    TRIAL = 'trial', 'Пробный период'


class BillingPeriod(models.TextChoices):
    """Периодичность оплаты после окончания пробного периода."""

    MONTHLY = 'monthly', 'Ежемесячно'
    YEARLY = 'yearly', 'Ежегодно'


class Category(models.Model):
    """Фиксированный справочник категорий, заполняется data-миграцией."""

    name = models.CharField('название', max_length=64, unique=True)
    slug = models.SlugField('код', max_length=64, unique=True)
    color = models.CharField(
        'цвет на диаграмме',
        max_length=7,
        help_text='HEX, например #4F46E5',
    )
    sort_order = models.PositiveSmallIntegerField('порядок', default=0)

    class Meta:
        ordering = ['sort_order', 'name']
        verbose_name = 'категория'
        verbose_name_plural = 'категории'

    def __str__(self):
        return self.name


class Service(models.Model):
    """Сервис, на который оформляется подписка (Netflix, Мегафон, VPS-хостинг).

    owner = NULL — запись из общего каталога, видна всем.
    owner = пользователь — свой сервис, которого нет в каталоге, виден только ему.
    """

    name = models.CharField('название', max_length=100)
    category = models.ForeignKey(
        Category,
        on_delete=models.PROTECT,
        related_name='services',
        verbose_name='категория',
    )
    website = models.URLField('сайт', blank=True)
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='custom_services',
        verbose_name='владелец',
    )

    class Meta:
        ordering = ['name']
        verbose_name = 'сервис'
        verbose_name_plural = 'сервисы'
        constraints = [
            # В PostgreSQL NULL != NULL, поэтому уникальность для каталога
            # и для пользовательских сервисов описана двумя условными индексами.
            models.UniqueConstraint(
                fields=['name'],
                condition=Q(owner__isnull=True),
                name='unique_catalog_service_name',
            ),
            models.UniqueConstraint(
                fields=['owner', 'name'],
                condition=Q(owner__isnull=False),
                name='unique_custom_service_name_per_owner',
            ),
        ]

    def __str__(self):
        return self.name

    @property
    def is_custom(self):
        return self.owner_id is not None


class PaymentMethod(models.Model):
    """Способ оплаты пользователя: карта, счёт и т.п."""

    class Kind(models.TextChoices):
        CARD = 'card', 'Банковская карта'
        ACCOUNT = 'account', 'Счёт / баланс'
        OTHER = 'other', 'Другое'

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='payment_methods',
        verbose_name='пользователь',
    )
    name = models.CharField('название', max_length=64, help_text='Например, «Т-Банк»')
    kind = models.CharField('тип', max_length=16, choices=Kind.choices, default=Kind.CARD)
    last4 = models.CharField('последние 4 цифры', max_length=4, blank=True)

    class Meta:
        ordering = ['name']
        verbose_name = 'способ оплаты'
        verbose_name_plural = 'способы оплаты'

    def __str__(self):
        return f'{self.name} *{self.last4}' if self.last4 else self.name


class Tag(models.Model):
    """Пользовательская метка подписки: «семья», «работа», «можно отменить»."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='tags',
        verbose_name='пользователь',
    )
    name = models.CharField('название', max_length=32)

    class Meta:
        ordering = ['name']
        verbose_name = 'тег'
        verbose_name_plural = 'теги'
        constraints = [
            models.UniqueConstraint(fields=['user', 'name'], name='unique_tag_name_per_user'),
        ]

    def __str__(self):
        return self.name


class Subscription(models.Model):
    """Подписка пользователя.

    Одна таблица на все типы оплаты: различие monthly / yearly / trial хранится
    в поле billing_type, а разное поведение (расчёт даты продления, стоимости
    в месяц) реализуется наследованием в сервисном слое — BillingCalculator.

    price — обычная цена за период. Для пробного периода это цена, которая
    начнёт списываться после trial_end_date с периодичностью billing_period_after_trial.
    """

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='subscriptions',
        verbose_name='пользователь',
    )
    service = models.ForeignKey(
        Service,
        on_delete=models.PROTECT,
        related_name='subscriptions',
        verbose_name='сервис',
    )
    payment_method = models.ForeignKey(
        PaymentMethod,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='subscriptions',
        verbose_name='способ оплаты',
    )
    tags = models.ManyToManyField(
        Tag,
        through='SubscriptionTag',
        related_name='subscriptions',
        blank=True,
        verbose_name='теги',
    )

    title = models.CharField(
        'название тарифа',
        max_length=100,
        blank=True,
        help_text='Необязательно, например «Семейный». По умолчанию — название сервиса.',
    )
    price = models.DecimalField(
        'цена за период, ₽',
        max_digits=10,
        decimal_places=2,
        validators=[MinValueValidator(0)],
    )
    billing_type = models.CharField(
        'тип оплаты',
        max_length=16,
        choices=BillingType.choices,
        default=BillingType.MONTHLY,
    )
    start_date = models.DateField('дата начала')
    trial_end_date = models.DateField('конец пробного периода', null=True, blank=True)
    billing_period_after_trial = models.CharField(
        'оплата после пробного периода',
        max_length=16,
        choices=BillingPeriod.choices,
        blank=True,
    )
    is_active = models.BooleanField('активна', default=True)
    notes = models.TextField('заметки', blank=True)

    created_at = models.DateTimeField('создана', auto_now_add=True)
    updated_at = models.DateTimeField('изменена', auto_now=True)

    class Meta:
        ordering = ['-is_active', 'service__name']
        verbose_name = 'подписка'
        verbose_name_plural = 'подписки'
        constraints = [
            models.CheckConstraint(
                condition=Q(price__gte=0),
                name='subscription_price_non_negative',
            ),
            # Для пробного периода обязательны дата окончания и периодичность после него.
            models.CheckConstraint(
                condition=~Q(billing_type=BillingType.TRIAL)
                | (Q(trial_end_date__isnull=False) & ~Q(billing_period_after_trial='')),
                name='subscription_trial_fields_required',
            ),
        ]
        indexes = [
            models.Index(fields=['user', 'is_active']),
        ]

    def __str__(self):
        return self.display_name

    @property
    def display_name(self):
        return f'{self.service.name} — {self.title}' if self.title else self.service.name

    @property
    def category(self):
        return self.service.category

    def clean(self):
        errors = {}
        if self.billing_type == BillingType.TRIAL:
            if not self.trial_end_date:
                errors['trial_end_date'] = 'Укажите дату окончания пробного периода.'
            if not self.billing_period_after_trial:
                errors['billing_period_after_trial'] = 'Укажите, как будет оплачиваться подписка после пробного периода.'
        if self.trial_end_date and self.start_date and self.trial_end_date < self.start_date:
            errors['trial_end_date'] = 'Пробный период не может закончиться раньше даты начала.'
        if self.payment_method_id and self.user_id and self.payment_method.user_id != self.user_id:
            errors['payment_method'] = 'Способ оплаты принадлежит другому пользователю.'
        if self.service_id and self.user_id and self.service.owner_id not in (None, self.user_id):
            errors['service'] = 'Этот сервис принадлежит другому пользователю.'
        if errors:
            raise ValidationError(errors)


class SubscriptionTag(models.Model):
    """Явная промежуточная таблица связи многие-ко-многим Subscription ↔ Tag."""

    subscription = models.ForeignKey(Subscription, on_delete=models.CASCADE, verbose_name='подписка')
    tag = models.ForeignKey(Tag, on_delete=models.CASCADE, verbose_name='тег')
    added_at = models.DateTimeField('добавлен', auto_now_add=True)

    class Meta:
        verbose_name = 'тег подписки'
        verbose_name_plural = 'теги подписок'
        constraints = [
            models.UniqueConstraint(fields=['subscription', 'tag'], name='unique_subscription_tag'),
        ]

    def __str__(self):
        return f'{self.subscription} — {self.tag}'

    def clean(self):
        if self.subscription_id and self.tag_id and self.subscription.user_id != self.tag.user_id:
            raise ValidationError('Тег и подписка должны принадлежать одному пользователю.')


class Payment(models.Model):
    """Фактическое списание по подписке.

    Сумма копируется в момент оплаты: если цена подписки потом изменится,
    история расходов останется верной.
    """

    subscription = models.ForeignKey(
        Subscription,
        on_delete=models.CASCADE,
        related_name='payments',
        verbose_name='подписка',
    )
    payment_method = models.ForeignKey(
        PaymentMethod,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='payments',
        verbose_name='способ оплаты',
    )
    amount = models.DecimalField(
        'сумма, ₽',
        max_digits=10,
        decimal_places=2,
        validators=[MinValueValidator(0)],
    )
    paid_at = models.DateField('дата списания')
    created_at = models.DateTimeField('создан', auto_now_add=True)

    class Meta:
        ordering = ['-paid_at']
        verbose_name = 'платёж'
        verbose_name_plural = 'платежи'
        constraints = [
            models.CheckConstraint(condition=Q(amount__gte=0), name='payment_amount_non_negative'),
        ]
        indexes = [
            models.Index(fields=['subscription', 'paid_at']),
        ]

    def __str__(self):
        return f'{self.subscription} — {self.amount} ₽ ({self.paid_at:%d.%m.%Y})'


class NotificationLog(models.Model):
    """Журнал отправленных уведомлений.

    Уникальный ключ (подписка, тип, канал, дата события) не даёт ежедневному
    cron-запуску отправить одно и то же напоминание повторно.
    """

    class Kind(models.TextChoices):
        TRIAL_ENDING = 'trial_ending', 'Окончание пробного периода'
        RENEWAL_UPCOMING = 'renewal_upcoming', 'Скорое продление'

    class Channel(models.TextChoices):
        EMAIL = 'email', 'Email'
        DASHBOARD = 'dashboard', 'Дашборд'

    subscription = models.ForeignKey(
        Subscription,
        on_delete=models.CASCADE,
        related_name='notifications',
        verbose_name='подписка',
    )
    kind = models.CharField('тип', max_length=32, choices=Kind.choices)
    channel = models.CharField('канал', max_length=16, choices=Channel.choices)
    event_date = models.DateField('дата события', help_text='Например, дата окончания пробного периода.')
    sent_at = models.DateTimeField('отправлено', auto_now_add=True)

    class Meta:
        ordering = ['-sent_at']
        verbose_name = 'уведомление'
        verbose_name_plural = 'журнал уведомлений'
        constraints = [
            models.UniqueConstraint(
                fields=['subscription', 'kind', 'channel', 'event_date'],
                name='unique_notification_per_event',
            ),
        ]

    def __str__(self):
        return f'{self.get_kind_display()} — {self.subscription} ({self.event_date:%d.%m.%Y})'
