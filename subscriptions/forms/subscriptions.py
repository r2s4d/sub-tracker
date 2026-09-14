from django import forms
from django.db.models import Q

from core.forms import BootstrapFormMixin, DateInput
from subscriptions.models import BillingType, Payment, Service, Subscription


class FieldGroup:
    """Часть полей формы для вывода отдельным разделом."""

    non_field_errors = ()
    hidden_fields = ()

    def __init__(self, form, *names):
        self.visible_fields = [form[name] for name in names]


class SubscriptionForm(BootstrapFormMixin, forms.ModelForm):
    """Форма подписки. Все выпадающие списки ограничены данными пользователя.

    Поля user в форме нет: владелец назначается во view, а чужую карту,
    тег или сервис нельзя выбрать — их просто нет в queryset, и Django
    отклонит такое значение как недопустимый вариант.
    """

    class Meta:
        model = Subscription
        fields = [
            'service', 'title', 'price', 'billing_type', 'start_date',
            'trial_end_date', 'billing_period_after_trial',
            'payment_method', 'tags', 'is_active', 'notes',
        ]
        widgets = {
            'start_date': DateInput(),
            'trial_end_date': DateInput(),
            'tags': forms.CheckboxSelectMultiple(),
            'notes': forms.Textarea(attrs={'rows': 3}),
        }
        help_texts = {
            'price': 'Для пробного периода — цена, которая начнёт списываться после его окончания.',
            'trial_end_date': 'Дата, после которой начнутся списания.',
            'billing_period_after_trial': 'Как часто будут списывать деньги после пробного периода.',
            'is_active': 'Отключённые подписки не учитываются в расходах.',
        }

    def __init__(self, *args, user, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = user
        # Модельный clean() сверяет владельца карты и сервиса по user_id,
        # поэтому пользователь нужен экземпляру ещё до валидации.
        self.instance.user = user

        # Общий каталог + свои сервисы пользователя.
        services = (
            Service.objects.filter(Q(owner__isnull=True) | Q(owner=user))
            .select_related('category')
            .order_by('category__sort_order', 'category__name', 'name')
        )
        service_field = self.fields['service']
        service_field.queryset = services
        # Своими choices заменяем плоский список: queryset по-прежнему валидирует выбор.
        service_field.choices = self._grouped_service_choices(services)

        self.fields['payment_method'].queryset = user.payment_methods.all()
        self.fields['payment_method'].empty_label = 'Не указан'
        self.fields['tags'].queryset = user.tags.all()
        # Поля триала обязательны только для пробного периода.
        is_trial = not self.is_bound or self.data.get(self.add_prefix('billing_type')) == BillingType.TRIAL
        for name in ('trial_end_date', 'billing_period_after_trial'):
            self.fields[name].required = is_trial
        self.fields['billing_period_after_trial'].choices = [('', 'Выберите периодичность')] + [
            c for c in self.fields['billing_period_after_trial'].choices if c[0]
        ]

    @staticmethod
    def _grouped_service_choices(services):
        """Варианты для <select> с <optgroup> по категориям."""
        groups = {}
        for service in services:
            label = f'{service.name} (свой)' if service.is_custom else service.name
            groups.setdefault(service.category.name, []).append((service.pk, label))
        return [('', 'Выберите сервис')] + list(groups.items())

    def clean(self):
        cleaned = super().clean()
        # Поля триала скрыты для других типов оплаты — не храним в них устаревшие значения.
        if cleaned.get('billing_type') != BillingType.TRIAL:
            cleaned['trial_end_date'] = None
            cleaned['billing_period_after_trial'] = ''
        return cleaned

    # Группы полей для разделов шаблона. FieldGroup повторяет интерфейс формы,
    # который нужен partials/form_fields.html, — без повтора ошибок формы в каждом разделе.
    @property
    def service_section(self):
        return FieldGroup(self, 'service', 'title')

    @property
    def billing_section(self):
        return FieldGroup(self, 'price', 'billing_type', 'start_date', 'payment_method')

    @property
    def trial_section(self):
        return FieldGroup(self, 'trial_end_date', 'billing_period_after_trial')

    @property
    def extra_section(self):
        return FieldGroup(self, 'is_active', 'notes')


class PaymentForm(BootstrapFormMixin, forms.ModelForm):
    """Отметка «оплачено»: фактическое списание по подписке."""

    class Meta:
        model = Payment
        fields = ['amount', 'paid_at', 'payment_method']
        widgets = {'paid_at': DateInput()}

    def __init__(self, *args, user, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['payment_method'].queryset = user.payment_methods.all()
        self.fields['payment_method'].empty_label = 'Не указан'
