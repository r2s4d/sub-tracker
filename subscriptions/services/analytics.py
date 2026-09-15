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
class CalendarCharge:
    pk: int
    name: str
    amount: Decimal
    color: str
    is_trial_end: bool


@dataclass
class CalendarDay:
    day: date
    in_month: bool
    is_today: bool
    is_past: bool
    charges: list[CalendarCharge] = field(default_factory=list)

    @property
    def total(self) -> Decimal:
        return sum((c.amount for c in self.charges), ZERO)


@dataclass
class CalendarMonth:
    month: date
    title: str
    weeks: list[list[CalendarDay]]
    total: Decimal
    charge_count: int


@dataclass
class MonthChange:
    """Что изменилось в расходах за последний месяц."""

    added: list[CategoryItem]
    removed: list[CategoryItem]

    @property
    def delta(self) -> Decimal:
        return sum((i.monthly for i in self.added), ZERO) - sum((i.monthly for i in self.removed), ZERO)

    @property
    def delta_abs(self) -> Decimal:
        return abs(self.delta)

    @property
    def delta_sign(self) -> str:
        return '+' if self.delta > 0 else '−' if self.delta < 0 else ''

    @property
    def has_changes(self) -> bool:
        return bool(self.added or self.removed)


@dataclass
class DashboardData:
    summary: SpendingSummary
    by_category: list[CategorySpending]
    months: list[MonthPoint]
    upcoming: list[Reminder]
    has_subscriptions: bool
    calendar: list[CalendarMonth] = field(default_factory=list)
    change: MonthChange | None = None
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


def charge_calendar(user, today: date, pairs=None, months: int = 2) -> list[CalendarMonth]:
    """Календарь списаний на текущий и следующий месяц: даты берутся у калькуляторов.

    Сетка — полные недели с понедельника; дни соседних месяцев помечены in_month=False.
    """
    pairs = _active_with_calculators(user) if pairs is None else pairs
    result = []
    for offset in range(months):
        month = add_months(today.replace(day=1), offset)
        month_end = date.fromordinal(add_months(month, 1).toordinal() - 1)

        by_day: dict[date, list[CalendarCharge]] = defaultdict(list)
        for subscription, calc in pairs:
            category = subscription.service.category
            for charge_day in calc.charge_dates(month, month_end):
                by_day[charge_day].append(CalendarCharge(
                    pk=subscription.pk,
                    name=subscription.display_name,
                    amount=subscription.price,
                    color=category.color,
                    is_trial_end=subscription.billing_type == BillingType.TRIAL and charge_day == subscription.trial_end_date,
                ))

        start = date.fromordinal(month.toordinal() - month.weekday())
        weeks, cursor = [], start
        while cursor <= month_end or cursor.weekday() != 0:
            if cursor.weekday() == 0:
                weeks.append([])
            weeks[-1].append(CalendarDay(
                day=cursor,
                in_month=cursor.month == month.month,
                is_today=cursor == today,
                is_past=cursor < today,
                charges=sorted(by_day.get(cursor, []), key=lambda c: c.amount, reverse=True),
            ))
            cursor = date.fromordinal(cursor.toordinal() + 1)

        all_charges = [c for charges in by_day.values() for c in charges]
        result.append(CalendarMonth(
            month=month,
            title=f'{MONTHS_FULL[month.month - 1]} {month.year}',
            weeks=weeks,
            total=sum((c.amount for c in all_charges), ZERO),
            charge_count=len(all_charges),
        ))
    return result


def month_payments(user, today: date, months: int = 12) -> list[list[dict]]:
    """Все платежи по месяцам (для раскрытия месяца на графике), от старых к новым."""
    current = today.replace(day=1)
    first = add_months(current, -(months - 1))
    buckets: dict[date, list[dict]] = defaultdict(list)
    payments = (
        Payment.objects.filter(subscription__user=user, paid_at__gte=first, paid_at__lt=add_months(current, 1))
        .select_related('subscription__service__category', 'payment_method')
        .order_by('-paid_at', 'subscription__service__name')
    )
    for payment in payments:
        category = payment.subscription.service.category
        buckets[payment.paid_at.replace(day=1)].append({
            'date': payment.paid_at.strftime('%d.%m'),
            'name': payment.subscription.display_name,
            'amount': float(payment.amount),
            'method': str(payment.payment_method) if payment.payment_method else '',
            'color': category.color,
            'pk': payment.subscription_id,
        })
    # Индексы совпадают с точками графика; следующий (плановый) месяц без платежей
    return [buckets.get(add_months(first, i), []) for i in range(months)] + [[]]


def month_change(user, today: date, pairs=None) -> MonthChange:
    """Добавленные и отключённые за последний месяц подписки.

    Добавленные — активные с датой начала за последний месяц. Отключённые — неактивные,
    изменённые за последний месяц: отдельной даты отключения в модели нет,
    поэтому это приближение по updated_at (записано в DECISIONS.md).
    """
    pairs = _active_with_calculators(user) if pairs is None else pairs
    since = add_months(today, -1)
    added = [
        CategoryItem(pk=s.pk, name=s.display_name, monthly=calc.monthly_cost(), note='')
        for s, calc in pairs
        if since < s.start_date <= today
    ]
    removed_qs = (
        Subscription.objects.filter(user=user, is_active=False, updated_at__date__gt=since)
        .select_related('service')
    )
    removed = [
        CategoryItem(pk=s.pk, name=s.display_name, monthly=BillingCalculatorFactory.create(s).monthly_cost(), note='')
        for s in removed_qs
    ]
    return MonthChange(added=added, removed=removed)


def build_dashboard(user, today: date) -> DashboardData:
    pairs = _active_with_calculators(user)
    summary = spending_summary(user, today, pairs)
    by_category = spending_by_category(user, pairs, today)
    months = monthly_spending(user, today, pairs=pairs)
    # Все списания на 30 дней: блок прокручивается, а не обрезает список
    upcoming = DashboardNotifier().deliver(user, collect_reminders(user, today, horizon_days=30))

    calendar = charge_calendar(user, today, pairs)
    change = month_change(user, today, pairs)

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
            'payments': month_payments(user, today),
        },
    }
    return DashboardData(
        summary=summary,
        by_category=by_category,
        months=months,
        upcoming=upcoming,
        has_subscriptions=Subscription.objects.filter(user=user).exists(),
        calendar=calendar,
        change=change,
        chart=chart,
    )
