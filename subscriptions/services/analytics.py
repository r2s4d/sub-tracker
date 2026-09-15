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

from core.templatetags.money import rub
from subscriptions.models import BillingType, Payment, Subscription

from .billing import BillingCalculator, BillingCalculatorFactory
from .dates import add_months
from .notifications import DashboardNotifier, Reminder, collect_reminders

ZERO = Decimal('0.00')
MONTHS_FULL = [
    'Январь', 'Февраль', 'Март', 'Апрель', 'Май', 'Июнь',
    'Июль', 'Август', 'Сентябрь', 'Октябрь', 'Ноябрь', 'Декабрь',
]
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
class CategoryItem:
    """Подписка внутри категории — для раскрытия сектора диаграммы."""

    pk: int
    name: str
    monthly: Decimal
    note: str  # «в месяц», «1 200 ₽ в год», «пробный до 16.09»


@dataclass
class CategorySpending:
    name: str
    slug: str
    color: str
    monthly: Decimal
    share: Decimal  # проценты, 0–100, один знак после запятой
    count: int
    items: list[CategoryItem] = field(default_factory=list)


@dataclass
class MonthPoint:
    month: date  # первое число месяца
    label: str
    actual: Decimal | None  # сколько реально оплачено (по Payment)
    planned: Decimal | None  # сколько спишется по плану (только текущий и следующий месяц)
    breakdown: list[tuple[str, Decimal]] = field(default_factory=list)  # за что заплатили, по убыванию


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


def _item_note(subscription: Subscription, calc: BillingCalculator, today: date | None) -> str:
    """Подпись к подписке в раскрытой категории: как на самом деле списываются деньги."""
    if subscription.billing_type == BillingType.TRIAL and today and calc.is_trial_active(today):
        return f'пробный до {subscription.trial_end_date:%d.%m}'
    period_months = getattr(getattr(calc, 'after_trial', calc), 'period_months', 1)
    if period_months == 12:
        return f'{rub(subscription.price)} в год'
    return 'в месяц'


def spending_by_category(user, pairs=None, today: date | None = None) -> list[CategorySpending]:
    pairs = _active_with_calculators(user) if pairs is None else pairs
    totals: dict[int, Decimal] = defaultdict(lambda: ZERO)
    counts: dict[int, int] = defaultdict(int)
    items: dict[int, list[CategoryItem]] = defaultdict(list)
    categories = {}
    for subscription, calc in pairs:
        category = subscription.service.category
        categories[category.pk] = category
        monthly = calc.monthly_cost()
        totals[category.pk] += monthly
        counts[category.pk] += 1
        items[category.pk].append(CategoryItem(
            pk=subscription.pk, name=subscription.display_name, monthly=monthly,
            note=_item_note(subscription, calc, today),
        ))

    grand_total = sum(totals.values(), ZERO)
    result = [
        CategorySpending(
            name=categories[pk].name,
            slug=categories[pk].slug,
            color=categories[pk].color,
            monthly=amount,
            share=(amount * 100 / grand_total).quantize(Decimal('0.1'), rounding=ROUND_HALF_UP),
            count=counts[pk],
            items=sorted(items[pk], key=lambda item: item.monthly, reverse=True),
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

    # Одна выборка: суммы по (месяц, подписка). Итог месяца — сумма разбивки.
    rows = (
        Payment.objects.filter(subscription__user=user, paid_at__gte=first, paid_at__lt=next_month)
        .annotate(month=TruncMonth('paid_at'))
        .values('month', 'subscription__service__name', 'subscription__title')
        .annotate(total=Sum('amount'))
    )
    paid: dict[date, Decimal] = defaultdict(lambda: ZERO)
    breakdown: dict[date, list[tuple[str, Decimal]]] = defaultdict(list)
    for row in rows:
        month = row['month'].date() if hasattr(row['month'], 'date') else row['month']
        name = row['subscription__service__name']
        if row['subscription__title']:
            name = f"{name} — {row['subscription__title']}"
        paid[month] += row['total']
        breakdown[month].append((name, row['total']))

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
            breakdown=sorted(breakdown.get(month, []), key=lambda pair: pair[1], reverse=True),
        ))
    return points


def build_dashboard(user, today: date) -> DashboardData:
    pairs = _active_with_calculators(user)
    summary = spending_summary(user, today, pairs)
    by_category = spending_by_category(user, pairs, today)
    months = monthly_spending(user, today, pairs=pairs)
    # Все списания на 30 дней: блок прокручивается, а не обрезает список
    upcoming = DashboardNotifier().deliver(user, collect_reminders(user, today, horizon_days=30))

    # Для Chart.js: деньги в float только на границе с JS.
    chart = {
        'categories': {
            'labels': [c.name for c in by_category],
            'values': [float(c.monthly) for c in by_category],
            'colors': [c.color for c in by_category],
            'shares': [float(c.share) for c in by_category],
            'counts': [c.count for c in by_category],
            'items': [[{'name': i.name, 'monthly': float(i.monthly), 'note': i.note} for i in c.items] for c in by_category],
        },
        'months': {
            'labels': [p.label for p in months],
            'titles': [f'{MONTHS_FULL[p.month.month - 1]} {p.month.year}' for p in months],
            'actual': [None if p.actual is None else float(p.actual) for p in months],
            'planned': [None if p.planned is None else float(p.planned) for p in months],
            'breakdown': [[[name, float(amount)] for name, amount in p.breakdown] for p in months],
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
