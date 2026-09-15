"""Дашборд: расчёты аналитики на фиксированных данных и view."""

from datetime import date
from decimal import Decimal
from unittest import mock

from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from subscriptions.models import BillingPeriod, BillingType, Payment, Service
from subscriptions.services.analytics import build_dashboard, monthly_spending, spending_by_category, spending_summary
from subscriptions.services.billing import BillingCalculatorFactory

from .utils import login_redirect_url, make_category, make_subscription, make_trial, make_user

TODAY = date(2026, 9, 14)


class AnalyticsDataMixin:
    """Набор: 300 ₽/мес, 1200 ₽/год, триал 600 ₽/мес после 20.09, отключённая 999 ₽/мес."""

    def setUp(self):
        self.user = make_user('dasha')
        self.other = make_user('egor')
        self.fun = make_category('fun', sort_order=1)
        self.work = make_category('work', sort_order=2)
        self.cinema = Service.objects.create(name='test-Кинотеатр', category=self.fun)
        self.ide = Service.objects.create(name='test-IDE', category=self.work)
        self.ai = Service.objects.create(name='test-Нейросеть', category=self.work)

        self.monthly = make_subscription(self.user, self.cinema, price=Decimal('300'), start_date=date(2026, 3, 5))
        self.yearly = make_subscription(
            self.user, self.ide, price=Decimal('1200'), billing_type=BillingType.YEARLY, start_date=date(2025, 10, 1),
        )
        self.trial = make_trial(
            self.user, self.ai, price=Decimal('600'), start_date=date(2026, 9, 6),
            trial_end_date=date(2026, 9, 20), billing_period_after_trial=BillingPeriod.MONTHLY,
        )
        self.inactive = make_subscription(self.user, self.cinema, price=Decimal('999'), is_active=False)
        # Чужая подписка — не должна попадать ни в одну цифру
        make_subscription(self.other, self.ide, price=Decimal('50000'), start_date=date(2026, 1, 1))

        Payment.objects.create(subscription=self.monthly, amount=Decimal('300'), paid_at=date(2026, 8, 5))
        Payment.objects.create(subscription=self.monthly, amount=Decimal('250'), paid_at=date(2026, 7, 5))
        Payment.objects.create(subscription=self.yearly, amount=Decimal('1200'), paid_at=date(2025, 10, 1))
        Payment.objects.create(subscription=self.monthly, amount=Decimal('300'), paid_at=date(2026, 9, 5))


class SpendingSummaryTests(AnalyticsDataMixin, TestCase):
    def test_totals(self):
        """В месяц: 300 + 1200/12 + 600 (триал по цене после окончания) = 1000; отключённая не считается."""
        summary = spending_summary(self.user, TODAY)
        self.assertEqual(summary.monthly_total, Decimal('1000.00'))
        self.assertEqual(summary.yearly_total, Decimal('12000.00'))
        self.assertEqual(summary.active_count, 3)
        self.assertEqual(summary.trial_count, 1)
        self.assertEqual(summary.trial_monthly, Decimal('600.00'))

    def test_equals_sum_of_calculators(self):
        """Итог — это просто сумма полиморфных monthly_cost(), без ветвлений по типу."""
        expected = sum(
            BillingCalculatorFactory.create(s).monthly_cost() for s in (self.monthly, self.yearly, self.trial)
        )
        self.assertEqual(spending_summary(self.user, TODAY).monthly_total, expected)

    def test_trial_no_longer_counted_as_trial_after_end(self):
        summary = spending_summary(self.user, date(2026, 9, 25))
        self.assertEqual(summary.trial_count, 0)
        self.assertEqual(summary.monthly_total, Decimal('1000.00'))

    def test_budget(self):
        profile = self.user.profile
        profile.monthly_budget = Decimal('800')
        profile.save()
        summary = spending_summary(self.user, TODAY)
        self.assertAlmostEqual(summary.budget_ratio, 1.25)
        self.assertEqual(summary.budget_over, Decimal('200.00'))
        self.assertEqual(summary.budget_left, Decimal('0.00'))

    def test_no_budget(self):
        summary = spending_summary(self.user, TODAY)
        self.assertIsNone(summary.budget_ratio)


class SpendingByCategoryTests(AnalyticsDataMixin, TestCase):
    def test_amounts_and_shares(self):
        """Работа: 100 + 600 = 700 (70%), развлечения: 300 (30%); сортировка по убыванию."""
        result = spending_by_category(self.user)
        self.assertEqual([c.slug for c in result], ['test-category-work', 'test-category-fun'])
        self.assertEqual([c.monthly for c in result], [Decimal('700.00'), Decimal('300.00')])
        self.assertEqual([c.share for c in result], [Decimal('70.0'), Decimal('30.0')])
        self.assertEqual(sum(c.share for c in result), Decimal('100.0'))
        self.assertEqual(result[0].count, 2)

    def test_empty_user(self):
        self.assertEqual(spending_by_category(make_user('empty')), [])


class MonthlySpendingTests(AnalyticsDataMixin, TestCase):
    def test_actual_payments_by_month(self):
        points = monthly_spending(self.user, TODAY)
        by_month = {p.month: p for p in points}
        self.assertEqual(len(points), 13)  # 12 месяцев + следующий
        self.assertEqual(points[0].month, date(2025, 10, 1))
        self.assertEqual(by_month[date(2025, 10, 1)].actual, Decimal('1200'))
        self.assertEqual(by_month[date(2026, 7, 1)].actual, Decimal('250'))
        self.assertEqual(by_month[date(2026, 9, 1)].actual, Decimal('300'))
        self.assertEqual(by_month[date(2026, 6, 1)].actual, Decimal('0'))
        self.assertIsNone(by_month[date(2026, 10, 1)].actual)

    def test_plan_for_current_and_next_month(self):
        """Сентябрь: кино 5.09 (300) + конец триала 20.09 (600). Октябрь: кино + триал + годовая IDE 1.10."""
        by_month = {p.month: p for p in monthly_spending(self.user, TODAY)}
        self.assertEqual(by_month[date(2026, 9, 1)].planned, Decimal('900.00'))
        self.assertEqual(by_month[date(2026, 10, 1)].planned, Decimal('2100.00'))
        self.assertIsNone(by_month[date(2026, 8, 1)].planned)

    def test_labels(self):
        labels = [p.label for p in monthly_spending(self.user, TODAY)]
        self.assertEqual(labels[0], 'окт 2025')
        self.assertEqual(labels[3], 'янв 2026')
        self.assertEqual(labels[4], 'фев')

    def test_other_users_payments_ignored(self):
        other_sub = self.other.subscriptions.get()
        Payment.objects.create(subscription=other_sub, amount=Decimal('50000'), paid_at=date(2026, 9, 1))
        by_month = {p.month: p for p in monthly_spending(self.user, TODAY)}
        self.assertEqual(by_month[date(2026, 9, 1)].actual, Decimal('300'))


class DashboardViewTests(AnalyticsDataMixin, TestCase):
    url = reverse('subscriptions:dashboard')

    def test_requires_login(self):
        self.client.logout()
        self.assertRedirects(self.client.get(self.url), login_redirect_url(self.url), fetch_redirect_response=False)

    def test_home_redirects_to_dashboard(self):
        self.client.force_login(self.user)
        self.assertRedirects(self.client.get(reverse('home')), self.url, fetch_redirect_response=False)

    @mock.patch('subscriptions.views.dashboard.timezone.localdate', return_value=TODAY)
    def test_renders_own_data_only(self, _):
        self.client.force_login(self.user)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['dashboard'].summary.monthly_total, Decimal('1000.00'))
        self.assertContains(response, 'id="chart-categories"')
        self.assertContains(response, 'id="dashboard-data"')
        self.assertContains(response, 'test-Нейросеть')  # ближайшее списание — конец триала
        self.assertNotContains(response, '50 000')

    def test_empty_user_sees_cta_without_charts(self):
        self.client.force_login(make_user('newbie'))
        response = self.client.get(self.url)
        self.assertContains(response, reverse('subscriptions:create'))
        self.assertNotContains(response, '<canvas')
        self.assertNotContains(response, 'chart.umd.min.js')

    def test_query_count_does_not_grow_with_subscriptions(self):
        """Калькуляторы работают в Python над одной выборкой — число запросов не зависит от числа подписок."""
        self.client.force_login(self.user)
        with CaptureQueriesContext(connection) as before:
            self.client.get(self.url)
        for i in range(8):
            make_subscription(self.user, self.cinema, price=Decimal('100'), title=f'доп {i}')
        with CaptureQueriesContext(connection) as after:
            self.client.get(self.url)
        self.assertEqual(len(before), len(after))

    def test_build_dashboard_chart_payload_is_json_ready(self):
        data = build_dashboard(self.user, TODAY)
        self.assertEqual(data.chart['categories']['values'], [700.0, 300.0])
        self.assertEqual(len(data.chart['months']['labels']), 13)
        self.assertIsNone(data.chart['months']['actual'][-1])
