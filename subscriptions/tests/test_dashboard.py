"""Дашборд: расчёты аналитики на фиксированных данных и view."""

from datetime import date
from decimal import Decimal
from unittest import mock

from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from subscriptions.models import BillingPeriod, BillingType, Payment, Service
from subscriptions.models import Subscription
from subscriptions.services.analytics import (
    build_dashboard,
    charge_calendar,
    month_change,
    month_payments,
    monthly_spending,
    spending_by_category,
    spending_summary,
)
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
        # Чужая подписка - не должна попадать ни в одну цифру
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
        """Итог - это просто сумма полиморфных monthly_cost(), без ветвлений по типу."""
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

    def test_items_for_drill_down(self):
        """Раскрытие категории: подписки внутри, по убыванию стоимости, с понятной подписью."""
        work = spending_by_category(self.user, today=TODAY)[0]
        self.assertEqual([i.name for i in work.items], ['test-Нейросеть', 'test-IDE'])
        self.assertEqual([i.monthly for i in work.items], [Decimal('600.00'), Decimal('100.00')])
        self.assertEqual(work.items[0].note, 'пробный до 20.09')
        self.assertEqual(work.items[1].note, '1 200,00 ₽ в год')
        self.assertNotIn(self.inactive.pk, [i.pk for c in spending_by_category(self.user) for i in c.items])

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

    def test_breakdown_by_subscription(self):
        """Подсказка месяца: за что именно заплатили, по убыванию суммы."""
        Payment.objects.create(subscription=self.yearly, amount=Decimal('50'), paid_at=date(2026, 9, 10))
        by_month = {p.month: p for p in monthly_spending(self.user, TODAY)}
        self.assertEqual(by_month[date(2026, 9, 1)].breakdown, [('test-Кинотеатр', Decimal('300')), ('test-IDE', Decimal('50'))])
        self.assertEqual(by_month[date(2026, 9, 1)].actual, Decimal('350'))
        self.assertEqual(by_month[date(2026, 6, 1)].breakdown, [])

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


class ChargeCalendarTests(AnalyticsDataMixin, TestCase):
    def test_current_month_charges(self):
        """Сентябрь: кинотеатр 5-го (300) и конец триала 20-го (600) - даты от калькуляторов."""
        september = charge_calendar(self.user, TODAY)[0]
        self.assertEqual(september.title, 'Сентябрь 2026')
        self.assertEqual((september.charge_count, september.total), (2, Decimal('900.00')))
        days = {d.day: d for week in september.weeks for d in week}
        self.assertEqual([c.name for c in days[date(2026, 9, 5)].charges], ['test-Кинотеатр'])
        trial_day = days[date(2026, 9, 20)]
        self.assertTrue(trial_day.charges[0].is_trial_end)
        self.assertEqual(trial_day.total, Decimal('600.00'))
        self.assertTrue(days[date(2026, 9, 14)].is_today)
        self.assertTrue(days[date(2026, 9, 5)].is_past)

    def test_grid_is_full_weeks_from_monday(self):
        """Сетка - полные недели с понедельника: 1 сентября 2026 - вторник, значит первая клетка 31 августа."""
        september = charge_calendar(self.user, TODAY)[0]
        self.assertEqual(len(september.weeks), 5)
        self.assertTrue(all(len(week) == 7 for week in september.weeks))
        first = september.weeks[0][0]
        self.assertEqual(first.day, date(2026, 8, 31))
        self.assertFalse(first.in_month)
        self.assertEqual(september.weeks[-1][-1].day, date(2026, 10, 4))

    def test_next_month_includes_yearly_charge(self):
        october = charge_calendar(self.user, TODAY)[1]
        self.assertEqual(october.charge_count, 3)
        self.assertEqual(october.total, Decimal('2100.00'))

    def test_inactive_and_foreign_subscriptions_excluded(self):
        names = {c.name for month in charge_calendar(self.user, TODAY) for week in month.weeks for d in week for c in d.charges}
        self.assertEqual(names, {'test-Кинотеатр', 'test-IDE', 'test-Нейросеть'})


class MonthPaymentsTests(AnalyticsDataMixin, TestCase):
    def test_payments_grouped_by_chart_month(self):
        """Индексы совпадают с точками графика: 12 месяцев и пустой следующий (плановый)."""
        months = month_payments(self.user, TODAY)
        self.assertEqual(len(months), 13)
        self.assertEqual([(p['name'], p['amount'], p['date']) for p in months[0]], [('test-IDE', 1200.0, '01.10')])
        self.assertEqual([p['amount'] for p in months[11]], [300.0])
        self.assertEqual(months[11][0]['pk'], self.monthly.pk)
        self.assertEqual(months[12], [])

    def test_other_users_payments_excluded(self):
        other_sub = self.other.subscriptions.get()
        Payment.objects.create(subscription=other_sub, amount=Decimal('50000'), paid_at=date(2026, 9, 1))
        self.assertNotIn(50000.0, [p['amount'] for month in month_payments(self.user, TODAY) for p in month])


class MonthChangeTests(AnalyticsDataMixin, TestCase):
    def test_added_and_removed(self):
        """Добавлена: подписка с датой начала за последний месяц. Отключена: неактивная, изменённая за месяц."""
        Subscription.objects.filter(pk=self.inactive.pk).update(updated_at=date(2026, 9, 1))
        change = month_change(self.user, TODAY)
        self.assertEqual([i.name for i in change.added], ['test-Нейросеть'])
        self.assertEqual([i.monthly for i in change.removed], [Decimal('999.00')])
        self.assertEqual(change.delta, Decimal('-399.00'))
        self.assertEqual((change.delta_sign, change.delta_abs), ('−', Decimal('399.00')))

    def test_old_deactivation_not_counted(self):
        Subscription.objects.filter(pk=self.inactive.pk).update(updated_at=date(2026, 6, 1))
        change = month_change(self.user, TODAY)
        self.assertEqual(change.removed, [])
        self.assertEqual(change.delta_sign, '+')

    def test_no_changes(self):
        Subscription.objects.filter(pk=self.inactive.pk).update(updated_at=date(2026, 6, 1))
        change = month_change(self.user, date(2027, 3, 1))
        self.assertFalse(change.has_changes)


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
        self.assertContains(response, 'test-Нейросеть')  # ближайшее списание - конец триала
        self.assertNotContains(response, '50 000')

    def test_one_screen_layout_class_only_with_data(self):
        """Раскладка «в один экран» включается только на обзоре с данными, другие страницы не затронуты."""
        self.client.force_login(self.user)
        self.assertContains(self.client.get(self.url), 'class="content content-dash"')
        self.assertNotContains(self.client.get(reverse('subscriptions:list')), 'content-dash')
        self.client.force_login(make_user('empty_layout'))
        self.assertNotContains(self.client.get(self.url), 'content-dash')

    def test_change_entries_limited_to_three_lines(self):
        """В верхней строке не больше трёх изменений, остальное: «и ещё N»."""
        for i in range(4):
            make_subscription(self.user, self.cinema, price=Decimal('10'), title=f'новая {i}', start_date=date(2026, 9, 1))
        self.client.force_login(self.user)
        with mock.patch('subscriptions.views.dashboard.timezone.localdate', return_value=TODAY):
            response = self.client.get(self.url)
        # 4 новые + триал из набора + отключённая подписка набора (изменена только что)
        self.assertEqual(len(response.context['dashboard'].change.entries), 6)
        self.assertContains(response, 'и ещё 3')

    def test_empty_user_sees_cta_without_charts(self):
        self.client.force_login(make_user('newbie'))
        response = self.client.get(self.url)
        self.assertContains(response, reverse('subscriptions:create'))
        self.assertNotContains(response, '<canvas')
        self.assertNotContains(response, 'chart.umd.min.js')

    def test_query_count_does_not_grow_with_subscriptions(self):
        """Калькуляторы работают в Python над одной выборкой - число запросов не зависит от числа подписок."""
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
        self.assertEqual(data.chart['months']['titles'][0], 'Октябрь 2025')
        self.assertEqual(data.chart['categories']['counts'], [2, 1])
        self.assertEqual(data.chart['categories']['items'][0][0], {'name': 'test-Нейросеть', 'monthly': 600.0, 'note': 'пробный до 20.09'})
        self.assertEqual(data.chart['months']['breakdown'][0], [['test-IDE', 1200.0]])
        self.assertIsNone(data.chart['months']['actual'][-1])

    def test_dashboard_uses_local_static_not_cdn(self):
        """Библиотеки грузятся с нашего сервера: внешний CDN мог не ответить, и диаграммы пропадали."""
        self.client.force_login(self.user)
        response = self.client.get(reverse('subscriptions:dashboard'))
        html = response.content.decode()
        self.assertIn('vendor/chartjs/chart.umd.min.js', html)
        self.assertIn('js/dashboard.js', html)
        for host in ('cdn.jsdelivr.net', 'fonts.googleapis.com', 'unpkg.com'):
            self.assertNotIn(host, html)
        self.assertContains(response, 'aria-expanded="false"')  # раскрываемая легенда
        self.assertContains(response, 'data-calendar')
        self.assertContains(response, 'data-month-detail')
