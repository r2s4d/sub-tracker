"""Сценарии владельца: создание, изменение, фильтры, платежи и удаление подписок."""

from datetime import date
from decimal import Decimal

from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone

from subscriptions.models import SubscriptionTag

from .utils import (
    BillingPeriod,
    BillingType,
    Payment,
    PaymentMethod,
    Service,
    Subscription,
    Tag,
    make_category,
    make_subscription,
    make_trial,
    make_user,
    subscription_post_data,
)


class SubscriptionViewTestBase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = make_user('owner_a')
        cls.other = make_user('other_b')
        cls.category = make_category('video', sort_order=1)
        cls.other_category = make_category('music', sort_order=2)
        cls.service = Service.objects.create(name='test-Видео', category=cls.category)
        cls.music_service = Service.objects.create(name='test-Музыка', category=cls.other_category)
        cls.card = PaymentMethod.objects.create(user=cls.user, name='test-Карта', last4='4242')
        cls.family = Tag.objects.create(user=cls.user, name='test-семья')
        cls.work = Tag.objects.create(user=cls.user, name='test-работа')

    def setUp(self):
        self.client.force_login(self.user)


class SubscriptionCreateTests(SubscriptionViewTestBase):
    url = reverse('subscriptions:create')

    def test_form_page_renders(self):
        """Страница новой подписки открывается."""
        self.assertEqual(self.client.get(self.url).status_code, 200)

    def test_create_monthly_owner_is_request_user(self):
        """Ежемесячная подписка создаётся от имени вошедшего, даже если в POST подброшен user другого."""
        data = subscription_post_data(
            self.service, title='test-Базовый', payment_method=self.card.pk, user=self.other.pk,
        )
        response = self.client.post(self.url, data)
        subscription = Subscription.objects.get(title='test-Базовый')
        self.assertRedirects(response, reverse('subscriptions:detail', args=[subscription.pk]))
        self.assertEqual(subscription.user, self.user)
        self.assertEqual(subscription.billing_type, BillingType.MONTHLY)
        self.assertEqual(subscription.price, Decimal('499.00'))
        self.assertEqual(subscription.payment_method, self.card)
        self.assertIsNone(subscription.trial_end_date)
        self.assertEqual(subscription.billing_period_after_trial, '')

    def test_create_trial_with_tags(self):
        """Пробная подписка с двумя тегами: создаются две записи SubscriptionTag."""
        data = subscription_post_data(
            self.service,
            title='test-Пробный',
            billing_type=BillingType.TRIAL,
            trial_end_date='2026-02-15',
            billing_period_after_trial=BillingPeriod.YEARLY,
            tags=[self.family.pk, self.work.pk],
        )
        self.client.post(self.url, data)
        subscription = Subscription.objects.get(title='test-Пробный')
        self.assertEqual(subscription.billing_type, BillingType.TRIAL)
        self.assertEqual(subscription.trial_end_date, date(2026, 2, 15))
        self.assertEqual(subscription.billing_period_after_trial, BillingPeriod.YEARLY)
        self.assertEqual(
            set(SubscriptionTag.objects.filter(subscription=subscription).values_list('tag', flat=True)),
            {self.family.pk, self.work.pk},
        )

    def test_trial_without_end_date_is_form_error(self):
        """Пробный период без даты окончания - ошибка формы, подписка не создана."""
        data = subscription_post_data(
            self.service, billing_type=BillingType.TRIAL, billing_period_after_trial=BillingPeriod.MONTHLY,
        )
        response = self.client.post(self.url, data)
        self.assertEqual(response.status_code, 200)
        self.assertIn('trial_end_date', response.context['form'].errors)
        self.assertFalse(Subscription.objects.exists())

    def test_trial_without_period_after_trial_is_form_error(self):
        """Пробный период без периодичности после него - ошибка формы, подписка не создана."""
        data = subscription_post_data(self.service, billing_type=BillingType.TRIAL, trial_end_date='2026-02-15')
        response = self.client.post(self.url, data)
        self.assertEqual(response.status_code, 200)
        self.assertIn('billing_period_after_trial', response.context['form'].errors)
        self.assertFalse(Subscription.objects.exists())

    def test_trial_ending_before_start_is_form_error(self):
        """Конец пробного периода раньше даты начала - ошибка формы, а не 500."""
        data = subscription_post_data(
            self.service, billing_type=BillingType.TRIAL, start_date='2026-03-01',
            trial_end_date='2026-02-01', billing_period_after_trial=BillingPeriod.MONTHLY,
        )
        response = self.client.post(self.url, data)
        self.assertEqual(response.status_code, 200)
        self.assertIn('trial_end_date', response.context['form'].errors)
        self.assertFalse(Subscription.objects.exists())

    def test_negative_price_is_form_error(self):
        """Отрицательная цена - ошибка формы, а не IntegrityError."""
        response = self.client.post(self.url, subscription_post_data(self.service, price='-1'))
        self.assertEqual(response.status_code, 200)
        self.assertIn('price', response.context['form'].errors)
        self.assertFalse(Subscription.objects.exists())

    def test_monthly_ignores_trial_fields(self):
        """Для ежемесячной подписки поля пробного периода из POST не сохраняются."""
        data = subscription_post_data(
            self.service, title='test-Лишнее', trial_end_date='2026-02-15',
            billing_period_after_trial=BillingPeriod.YEARLY,
        )
        self.client.post(self.url, data)
        subscription = Subscription.objects.get(title='test-Лишнее')
        self.assertIsNone(subscription.trial_end_date)
        self.assertEqual(subscription.billing_period_after_trial, '')


class SubscriptionUpdateTests(SubscriptionViewTestBase):
    def test_update_saves_changes(self):
        """Изменение цены, тарифа и тегов сохраняется."""
        subscription = make_subscription(self.user, self.service, title='test-Старый')
        subscription.tags.add(self.family)
        url = reverse('subscriptions:update', args=[subscription.pk])
        data = subscription_post_data(self.music_service, title='test-Новый', price='799.00', tags=[self.work.pk])
        response = self.client.post(url, data)
        self.assertRedirects(response, reverse('subscriptions:detail', args=[subscription.pk]))
        subscription.refresh_from_db()
        self.assertEqual(subscription.title, 'test-Новый')
        self.assertEqual(subscription.service, self.music_service)
        self.assertEqual(subscription.price, Decimal('799.00'))
        self.assertEqual(list(subscription.tags.all()), [self.work])
        self.assertEqual(subscription.user, self.user)

    def test_switch_trial_to_monthly_clears_trial_fields(self):
        """Смена пробного периода на ежемесячную оплату очищает поля триала, даже если они пришли в POST."""
        subscription = make_trial(self.user, self.service)
        url = reverse('subscriptions:update', args=[subscription.pk])
        data = subscription_post_data(
            self.service, billing_type=BillingType.MONTHLY,
            trial_end_date='2026-01-15', billing_period_after_trial=BillingPeriod.MONTHLY,
        )
        self.client.post(url, data)
        subscription.refresh_from_db()
        self.assertEqual(subscription.billing_type, BillingType.MONTHLY)
        self.assertIsNone(subscription.trial_end_date)
        self.assertEqual(subscription.billing_period_after_trial, '')

    def test_update_form_renders_with_instance(self):
        """Форма редактирования открывается с данными подписки."""
        subscription = make_subscription(self.user, self.service, title='test-Текущий')
        response = self.client.get(reverse('subscriptions:update', args=[subscription.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['form'].instance, subscription)
        self.assertContains(response, 'test-Текущий')


class SubscriptionListFilterTests(SubscriptionViewTestBase):
    url = reverse('subscriptions:list')

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.monthly = make_subscription(cls.user, cls.service, title='test-Ежемесячная')
        cls.monthly.tags.add(cls.family)
        cls.yearly = make_subscription(
            cls.user, cls.music_service, title='test-Ежегодная', billing_type=BillingType.YEARLY,
        )
        cls.yearly.tags.add(cls.work)
        cls.trial = make_trial(cls.user, cls.service, title='test-Пробная')
        cls.inactive = make_subscription(cls.user, cls.music_service, title='test-Отключённая', is_active=False)

    def listed(self, **params):
        response = self.client.get(self.url, params)
        self.assertEqual(response.status_code, 200)
        return set(response.context['subscriptions'])

    def test_default_shows_only_active(self):
        """По умолчанию показываются только активные подписки."""
        self.assertEqual(self.listed(), {self.monthly, self.yearly, self.trial})

    def test_status_inactive(self):
        """status=inactive - только отключённые."""
        self.assertEqual(self.listed(status='inactive'), {self.inactive})

    def test_status_all(self):
        """status=all - все подписки."""
        self.assertEqual(self.listed(status='all'), {self.monthly, self.yearly, self.trial, self.inactive})

    def test_unknown_status_falls_back_to_active(self):
        """Неизвестный статус молча заменяется на «активные»."""
        self.assertEqual(self.listed(status='hacker'), {self.monthly, self.yearly, self.trial})

    def test_billing_type_filter(self):
        """billing_type=yearly - только ежегодные, billing_type=trial - только пробные."""
        self.assertEqual(self.listed(billing_type=BillingType.YEARLY), {self.yearly})
        self.assertEqual(self.listed(billing_type=BillingType.TRIAL), {self.trial})

    def test_category_filter(self):
        """category=<slug> - подписки на сервисы этой категории (с учётом статуса)."""
        self.assertEqual(self.listed(category=self.other_category.slug), {self.yearly})
        self.assertEqual(self.listed(category=self.other_category.slug, status='all'), {self.yearly, self.inactive})

    def test_tag_filter(self):
        """tag=<id> - подписки с этим тегом."""
        self.assertEqual(self.listed(tag=self.family.pk), {self.monthly})

    def test_non_numeric_tag_is_ignored(self):
        """Нечисловой tag игнорируется, а не роняет страницу."""
        self.assertEqual(self.listed(tag='abc'), {self.monthly, self.yearly, self.trial})

    def test_empty_filter_result_is_distinguished_from_no_subscriptions(self):
        """Если фильтр ничего не нашёл, страница говорит «Ничего не найдено», а не «Подписок пока нет»."""
        response = self.client.get(self.url, {'billing_type': BillingType.YEARLY, 'category': self.category.slug})
        self.assertContains(response, 'Ничего не найдено')
        self.assertNotContains(response, 'Подписок пока нет')

    def test_list_query_count_does_not_grow_with_subscriptions(self):
        """Число SQL-запросов списка не зависит от количества подписок (нет N+1)."""
        def count_queries():
            with CaptureQueriesContext(connection) as ctx:
                response = self.client.get(self.url, {'status': 'all'})
            self.assertEqual(response.status_code, 200)
            return len(ctx.captured_queries), len(response.context['subscriptions'])

        few_queries, few = count_queries()
        for i in range(8):
            extra = make_subscription(self.user, self.service, title=f'test-Доп-{i}', payment_method=self.card)
            extra.tags.add(self.family, self.work)
        many_queries, many = count_queries()
        self.assertEqual((few, many), (4, 12))
        self.assertEqual(many_queries, few_queries)


class SubscriptionDetailAndPaymentsTests(SubscriptionViewTestBase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.subscription = make_subscription(
            cls.user, cls.service, price=Decimal('349.00'), payment_method=cls.card,
        )

    def detail_url(self):
        return reverse('subscriptions:detail', args=[self.subscription.pk])

    def test_detail_shows_payments_and_total(self):
        """Карточка подписки показывает платежи и сумму «всего оплачено»."""
        Payment.objects.create(subscription=self.subscription, amount=Decimal('100.00'), paid_at=date(2026, 1, 5))
        Payment.objects.create(subscription=self.subscription, amount=Decimal('250.50'), paid_at=date(2026, 2, 5))
        response = self.client.get(self.detail_url())
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.context['payments']), 2)
        self.assertEqual(response.context['total_paid'], Decimal('350.50'))
        self.assertContains(response, '05.01.2026')
        self.assertContains(response, '05.02.2026')

    def test_detail_without_payments_has_zero_total(self):
        """Без платежей сумма равна нулю."""
        response = self.client.get(self.detail_url())
        self.assertEqual(response.context['total_paid'], 0)
        self.assertContains(response, 'Платежей пока нет')

    def test_payment_form_defaults(self):
        """Форма «оплачено» заполнена ценой подписки, сегодняшней датой и её способом оплаты."""
        initial = self.client.get(self.detail_url()).context['payment_form'].initial
        self.assertEqual(initial['amount'], Decimal('349.00'))
        self.assertEqual(initial['paid_at'], timezone.localdate())
        self.assertEqual(initial['payment_method'], self.card.pk)

    def test_mark_paid_with_defaults_creates_payment(self):
        """Отправка формы «оплачено» со значениями по умолчанию создаёт Payment."""
        initial = self.client.get(self.detail_url()).context['payment_form'].initial
        response = self.client.post(
            reverse('subscriptions:mark-paid', args=[self.subscription.pk]),
            {
                'amount': str(initial['amount']),
                'paid_at': initial['paid_at'].isoformat(),
                'payment_method': initial['payment_method'],
            },
        )
        self.assertRedirects(response, self.detail_url())
        payment = Payment.objects.get(subscription=self.subscription)
        self.assertEqual(payment.amount, Decimal('349.00'))
        self.assertEqual(payment.paid_at, timezone.localdate())
        self.assertEqual(payment.payment_method, self.card)

    def test_invalid_mark_paid_does_not_create_payment(self):
        """Некорректная отметка оплаты (отрицательная сумма, нет даты) - платёж не создан, показана ошибка."""
        response = self.client.post(
            reverse('subscriptions:mark-paid', args=[self.subscription.pk]),
            {'amount': '-5', 'paid_at': '', 'payment_method': ''},
            follow=True,
        )
        self.assertRedirects(response, self.detail_url())
        self.assertFalse(Payment.objects.exists())
        self.assertContains(response, 'Платёж не записан')

    def test_payment_delete(self):
        """Удаление платежа - запись удалена, возврат на карточку подписки."""
        payment = Payment.objects.create(
            subscription=self.subscription, amount=Decimal('349.00'), paid_at=date(2026, 2, 1),
        )
        response = self.client.post(reverse('subscriptions:payment-delete', args=[payment.pk]))
        self.assertRedirects(response, self.detail_url())
        self.assertFalse(Payment.objects.filter(pk=payment.pk).exists())
        self.assertTrue(Subscription.objects.filter(pk=self.subscription.pk).exists())

    def test_get_on_mark_paid_is_not_allowed(self):
        """GET на «оплачено» - 405, платёж не создаётся."""
        response = self.client.get(reverse('subscriptions:mark-paid', args=[self.subscription.pk]))
        self.assertEqual(response.status_code, 405)
        self.assertFalse(Payment.objects.exists())

    def test_get_on_payment_delete_is_not_allowed(self):
        """GET на удаление платежа - 405, платёж остаётся."""
        payment = Payment.objects.create(
            subscription=self.subscription, amount=Decimal('349.00'), paid_at=date(2026, 2, 1),
        )
        response = self.client.get(reverse('subscriptions:payment-delete', args=[payment.pk]))
        self.assertEqual(response.status_code, 405)
        self.assertTrue(Payment.objects.filter(pk=payment.pk).exists())


class SubscriptionDeleteTests(SubscriptionViewTestBase):
    def test_confirm_page_warns_about_payments(self):
        """Страница подтверждения предупреждает, сколько платежей удалится."""
        subscription = make_subscription(self.user, self.service)
        Payment.objects.create(subscription=subscription, amount=Decimal('1.00'), paid_at=date(2026, 2, 1))
        Payment.objects.create(subscription=subscription, amount=Decimal('2.00'), paid_at=date(2026, 3, 1))
        response = self.client.get(reverse('subscriptions:delete', args=[subscription.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, '2 платежа')

    def test_delete_cascades_payments_and_tag_links(self):
        """Удаление подписки удаляет её платежи и связи с тегами; сами теги и карта остаются."""
        subscription = make_subscription(self.user, self.service, payment_method=self.card)
        subscription.tags.add(self.family)
        Payment.objects.create(subscription=subscription, amount=Decimal('1.00'), paid_at=date(2026, 2, 1))
        response = self.client.post(reverse('subscriptions:delete', args=[subscription.pk]))
        self.assertRedirects(response, reverse('subscriptions:list'))
        self.assertFalse(Subscription.objects.filter(pk=subscription.pk).exists())
        self.assertFalse(Payment.objects.exists())
        self.assertFalse(SubscriptionTag.objects.exists())
        self.assertTrue(Tag.objects.filter(pk=self.family.pk).exists())
        self.assertTrue(PaymentMethod.objects.filter(pk=self.card.pk).exists())


class LiveFiltersPartialTests(TestCase):
    """Фильтры без перезагрузки: по заголовку X-Partial отдаётся только блок результатов."""

    def setUp(self):
        self.user = make_user('live')
        category = make_category('live')
        self.monthly = make_subscription(self.user, Service.objects.create(name='test-помесячно', category=category))
        self.yearly = make_subscription(
            self.user, Service.objects.create(name='test-годовая', category=category), billing_type='yearly',
        )
        self.client.force_login(self.user)
        self.url = reverse('subscriptions:list')

    def test_partial_contains_only_results(self):
        response = self.client.get(self.url, {'billing_type': 'yearly'}, HTTP_X_PARTIAL='results')
        html = response.content.decode()
        self.assertTemplateUsed(response, 'subscriptions/subscription_list_results.html')
        self.assertTemplateNotUsed(response, 'base.html')
        self.assertIn('test-годовая', html)
        self.assertNotIn('test-помесячно', html)
        self.assertIn('X-Partial', response['Vary'])

    def test_full_page_without_header(self):
        response = self.client.get(self.url, {'billing_type': 'yearly'})
        self.assertTemplateUsed(response, 'base.html')
        self.assertNotContains(response, 'test-помесячно')

    def test_partial_requires_login(self):
        self.client.logout()
        response = self.client.get(self.url, HTTP_X_PARTIAL='results')
        self.assertEqual(response.status_code, 302)
