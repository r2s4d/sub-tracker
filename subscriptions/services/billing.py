"""Расчёт стоимости подписки и дат списаний.

Здесь живёт ООП-часть проекта (ТЗ, раздел 2, «вариант Б»):

    BillingCalculator (абстрактный класс)
    ├── PeriodicBillingCalculator (общая логика регулярных списаний)
    │   ├── MonthlyBillingCalculator
    │   └── YearlyBillingCalculator
    └── TrialBillingCalculator (пробный период, затем делегирует периодическому)

    BillingCalculatorFactory.create(subscription) → нужный калькулятор по billing_type

В базе данных подписка - одна таблица с полем billing_type. Разное поведение
для разных типов оплаты - не в ORM, а в этих классах. Код, который считает
расходы (дашборд, уведомления), работает с любым калькулятором одинаково:
вызывает monthly_cost() и calculate_next_renewal(), не проверяя тип подписки.
Это и есть полиморфизм: один интерфейс - разные реализации.
"""

from abc import ABC, abstractmethod
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from django.utils import timezone

from subscriptions.models import BillingPeriod, BillingType, Subscription

from .dates import add_months, months_between

CENT = Decimal('0.01')


def _money(value: Decimal) -> Decimal:
    return value.quantize(CENT, rounding=ROUND_HALF_UP)


class BillingCalculator(ABC):
    """Общий интерфейс всех калькуляторов.

    Абстрактный класс нельзя создать напрямую - только наследника, который
    реализовал оба абстрактных метода.
    """

    def __init__(self, subscription: Subscription):
        self.subscription = subscription

    @abstractmethod
    def calculate_next_renewal(self, today: date | None = None) -> date:
        """Дата ближайшего списания, начиная с today включительно."""

    @abstractmethod
    def monthly_cost(self) -> Decimal:
        """Сколько подписка стоит в пересчёте на один месяц."""

    @abstractmethod
    def charge_dates(self, start: date, end: date) -> list[date]:
        """Все даты списаний в интервале [start, end]."""

    # Методы ниже одинаковы для всех наследников и опираются на абстрактные.

    def yearly_cost(self) -> Decimal:
        """Годовой эквивалент: месячные подписки тоже пересчитываются в год."""
        return _money(self.monthly_cost() * 12)

    def days_until_renewal(self, today: date | None = None) -> int:
        today = today or timezone.localdate()
        return (self.calculate_next_renewal(today) - today).days

    def expected_amount(self, start: date, end: date) -> Decimal:
        """Сколько по плану спишется за интервал (например, прогноз на месяц)."""
        return _money(self.subscription.price * len(self.charge_dates(start, end)))


class PeriodicBillingCalculator(BillingCalculator):
    """Регулярные списания раз в period_months месяцев от опорной даты.

    Даты считаются от опорной даты (start + k·период), а не от предыдущего
    списания: так подписка от 31 января спишется 28 февраля, а в марте снова 31-го,
    а не «уедет» на 28-е навсегда.
    """

    period_months: int  # задаётся в наследниках

    def __init__(self, subscription: Subscription, anchor: date | None = None):
        super().__init__(subscription)
        # Для обычной подписки опорная дата - начало, для бывшего триала - его конец.
        self.anchor = anchor or subscription.start_date

    def _charge_at(self, index: int) -> date:
        return add_months(self.anchor, index * self.period_months)

    def calculate_next_renewal(self, today: date | None = None) -> date:
        today = today or timezone.localdate()
        if today <= self.anchor:
            return self.anchor
        index = months_between(self.anchor, today) // self.period_months
        charge = self._charge_at(index)
        return charge if charge >= today else self._charge_at(index + 1)

    def charge_dates(self, start: date, end: date) -> list[date]:
        dates, charge = [], self.calculate_next_renewal(start)
        index = months_between(self.anchor, charge) // self.period_months
        while charge <= end:
            dates.append(charge)
            index += 1
            charge = self._charge_at(index)
        return dates


class MonthlyBillingCalculator(PeriodicBillingCalculator):
    period_months = 1

    def monthly_cost(self) -> Decimal:
        return _money(self.subscription.price)


class YearlyBillingCalculator(PeriodicBillingCalculator):
    period_months = 12

    def monthly_cost(self) -> Decimal:
        return _money(self.subscription.price / 12)

    def yearly_cost(self) -> Decimal:
        # Переопределение: годовая цена известна точно, пересчёт через
        # округлённую месячную дал бы 741,67 × 12 = 8 900,04 вместо 8 900.
        return _money(self.subscription.price)


class TrialBillingCalculator(BillingCalculator):
    """Пробный период: до trial_end_date бесплатно, потом - обычная периодическая оплата.

    Поведение «после триала» не дублируется, а делегируется калькулятору
    нужного периода (композиция): первое списание - в день окончания триала.
    """

    _after_trial_classes = {
        BillingPeriod.MONTHLY: MonthlyBillingCalculator,
        BillingPeriod.YEARLY: YearlyBillingCalculator,
    }

    def __init__(self, subscription: Subscription):
        super().__init__(subscription)
        after_trial_class = self._after_trial_classes[subscription.billing_period_after_trial]
        self.after_trial = after_trial_class(subscription, anchor=subscription.trial_end_date)

    def is_trial_active(self, today: date | None = None) -> bool:
        today = today or timezone.localdate()
        return today < self.subscription.trial_end_date

    def days_until_trial_end(self, today: date | None = None) -> int:
        today = today or timezone.localdate()
        return (self.subscription.trial_end_date - today).days

    def calculate_next_renewal(self, today: date | None = None) -> date:
        return self.after_trial.calculate_next_renewal(today)

    def monthly_cost(self) -> Decimal:
        # Считаем по цене после триала: это расход, который начнётся,
        # если не отменить подписку, - именно его важно видеть в бюджете.
        return self.after_trial.monthly_cost()

    def yearly_cost(self) -> Decimal:
        return self.after_trial.yearly_cost()

    def charge_dates(self, start: date, end: date) -> list[date]:
        return self.after_trial.charge_dates(start, end)


class BillingCalculatorFactory:
    """Фабрика: выбирает класс калькулятора по полю billing_type.

    Вызывающему коду не нужно знать, какие бывают калькуляторы. Чтобы добавить
    новый тип оплаты (например, квартальный), достаточно написать класс
    и добавить строку в _registry - остальной код не меняется.
    """

    _registry: dict[str, type[BillingCalculator]] = {
        BillingType.MONTHLY: MonthlyBillingCalculator,
        BillingType.YEARLY: YearlyBillingCalculator,
        BillingType.TRIAL: TrialBillingCalculator,
    }

    @classmethod
    def create(cls, subscription: Subscription) -> BillingCalculator:
        try:
            calculator_class = cls._registry[subscription.billing_type]
        except KeyError:
            raise ValueError(f'Неизвестный тип оплаты: {subscription.billing_type!r}') from None
        return calculator_class(subscription)
