"""Данные для дашборда: итоги, расходы по категориям, динамика по месяцам.

Функции не знают про HTTP и шаблоны — принимают пользователя и дату «сегодня»,
поэтому их легко тестировать на фиксированных датах.

Здесь виден полиморфизм из billing.py в действии: итоги считаются как сумма
calculator.monthly_cost() по всем подпискам, без единой проверки billing_type.
"""

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from django.db.models import Sum
from django.db.models.functions import TruncMonth

from subscriptions.models import Payment, Subscription

from .billing import BillingCalculator, BillingCalculatorFactory
from .dates import add_months
from .notifications import DashboardNotifier, Reminder, collect_reminders

ZERO = Decimal('0.00')
MONTHS_SHORT = ['янв', 'фев', 'мар', 'апр', 'май', 'июн', 'июл', 'авг', 'сен', 'окт', 'ноя', 'дек']


@dataclass
class SpendingSummary:
    monthly_total: Decimal
    yearly_total: Decimal
    active_count: int
    trial_count: int
    trial_monthly: Decimal  # часть месячной суммы от подписок, которые ещё на пробном периоде
    budget: Decimal | None
    budget_ratio: float | None  # 0.8 = потрачено 80% бюджета; >1 — бюджет превышен

    @property
    def budget_left(self) -> Decimal | None:
        return None if self.budget is None else max(self.budget - self.monthly_total, ZERO)

    @property
    def budget_over(self) -> Decimal | None:
        return None if self.budget is None else max(self.monthly_total - self.budget, ZERO)


@dataclass
class CategorySpending:
    name: str
    slug: str
    color: str
    monthly: Decimal
    share: Decimal  # проценты, 0–100, один знак после запятой
    count: int


@dataclass
class MonthPoint:
    month: date  # первое число месяца
    label: str
    actual: Decimal | None  # сколько реально оплачено (по Payment)
    planned: Decimal | None  # сколько спишется по плану (только текущий и следующий месяц)


@dataclass
class DashboardData:
    summary: SpendingSummary
    by_category: list[CategorySpending]
    months: list[MonthPoint]
    upcoming: list[Reminder]
    has_subscriptions: bool
    chart: dict = field(default_factory=dict)


def _active_with_calculators(user) -> list[tuple[Subscription, BillingCalculator]]:
    """Один запрос за активными подписками; калькуляторы работают уже в Python."""
    subscriptions = (
        Subscription.objects.filter(user=user, is_active=True)
        .select_related('service__category')
        .order_by('service__category__sort_order', 'service__name')
    )
    return [(s, BillingCalculatorFactory.create(s)) for s in subscriptions]


def spending_summary(user, today: date, pairs=None) -> SpendingSummary:
    pairs = _active_with_calculators(user) if pairs is None else pairs
    monthly_total = sum((calc.monthly_cost() for _, calc in pairs), ZERO)
    yearly_total = sum((calc.yearly_cost() for _, calc in pairs), ZERO)

    # Пробные периоды — через метод калькулятора, а не проверку поля модели.
    on_trial = [calc for _, calc in pairs if getattr(calc, 'is_trial_active', None) and calc.is_trial_active(today)]
    budget = user.profile.monthly_budget
    return SpendingSummary(
        monthly_total=monthly_total,
        yearly_total=yearly_total,
        active_count=len(pairs),
        trial_count=len(on_trial),
        trial_monthly=sum((calc.monthly_cost() for calc in on_trial), ZERO),
        budget=budget,
        budget_ratio=float(monthly_total / budget) if budget else None,
    )


def spending_by_category(user, pairs=None) -> list[CategorySpending]:
    pairs = _active_with_calculators(user) if pairs is None else pairs
    totals: dict[int, Decimal] = defaultdict(lambda: ZERO)
    counts: dict[int, int] = defaultdict(int)
    categories = {}
    for subscription, calc in pairs:
        category = subscription.service.category
        categories[category.pk] = category
        totals[category.pk] += calc.monthly_cost()
        counts[category.pk] += 1

    grand_total = sum(totals.values(), ZERO)
    result = [
        CategorySpending(
            name=categories[pk].name,
            slug=categories[pk].slug,
            color=categories[pk].color,
            monthly=amount,
            share=(amount * 100 / grand_total).quantize(Decimal('0.1'), rounding=ROUND_HALF_UP),
            count=counts[pk],
        )
        for pk, amount in totals.items()
        if amount > 0
    ]
    return sorted(result, key=lambda c: c.monthly, reverse=True)


def _month_label(month: date, is_first: bool) -> str:
    label = MONTHS_SHORT[month.month - 1]
    return f'{label} {month.year}' if is_first or month.month == 1 else label


def monthly_spending(user, today: date, months: int = 12, pairs=None) -> list[MonthPoint]:
    """Оплачено по месяцам за последние `months` месяцев + план на текущий и следующий.

    Факт берётся из Payment (одна агрегирующая выборка), план — из калькуляторов:
    сколько списаний каждой активной подписки попадает в месяц.
    """
    pairs = _active_with_calculators(user) if pairs is None else pairs
    current = today.replace(day=1)
    first = add_months(current, -(months - 1))
    next_month = add_months(current, 1)

    paid = dict(
        Payment.objects.filter(subscription__user=user, paid_at__gte=first, paid_at__lt=next_month)
        .annotate(month=TruncMonth('paid_at'))
        .values('month')
        .annotate(total=Sum('amount'))
        .values_list('month', 'total')
    )
    paid = {(m.date() if hasattr(m, 'date') else m): total for m, total in paid.items()}

    def planned_for(month_start: date) -> Decimal:
        month_end = add_months(month_start, 1).replace(day=1)
        last_day = date.fromordinal(month_end.toordinal() - 1)
        return sum((calc.expected_amount(month_start, last_day) for _, calc in pairs), ZERO)

    points = []
    for index in range(months + 1):
        month = add_months(first, index)
        is_future = month > current
        points.append(MonthPoint(
            month=month,
            label=_month_label(month, index == 0),
            actual=None if is_future else paid.get(month, ZERO),
            planned=planned_for(month) if month >= current else None,
        ))
    return points


def build_dashboard(user, today: date) -> DashboardData:
    pairs = _active_with_calculators(user)
    summary = spending_summary(user, today, pairs)
    by_category = spending_by_category(user, pairs)
    months = monthly_spending(user, today, pairs=pairs)
    upcoming = DashboardNotifier(limit=6).deliver(user, collect_reminders(user, today, horizon_days=30))

    # Для Chart.js: деньги в float только на границе с JS.
    chart = {
        'categories': {
            'labels': [c.name for c in by_category],
            'values': [float(c.monthly) for c in by_category],
            'colors': [c.color for c in by_category],
            'shares': [float(c.share) for c in by_category],
        },
        'months': {
            'labels': [p.label for p in months],
            'actual': [None if p.actual is None else float(p.actual) for p in months],
            'planned': [None if p.planned is None else float(p.planned) for p in months],
        },
    }
    return DashboardData(
        summary=summary,
        by_category=by_category,
        months=months,
        upcoming=upcoming,
        has_subscriptions=Subscription.objects.filter(user=user).exists(),
        chart=chart,
    )
