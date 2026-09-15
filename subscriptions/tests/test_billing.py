"""Тесты сервисного слоя расчёта оплаты (subscriptions/services/billing.py, dates.py).

Тесты одновременно служат документацией к ООП-части проекта:
- абстрактный класс BillingCalculator и его наследники;
- полиморфизм: один интерфейс monthly_cost() / calculate_next_renewal() для любых подписок;
- фабрика BillingCalculatorFactory, выбирающая класс по billing_type.

Везде используются несохранённые объекты Subscription(...) - расчёт не ходит в БД,
поэтому хватает SimpleTestCase. Дата «сегодня» всегда передаётся явно, чтобы
результат не зависел от дня запуска тестов.
"""

from datetime import date
from decimal import Decimal

from django.test import SimpleTestCase

from subscriptions.models import BillingPeriod, BillingType, Subscription
from subscriptions.services.billing import (
    BillingCalculator,
    BillingCalculatorFactory,
    MonthlyBillingCalculator,
    PeriodicBillingCalculator,
    TrialBillingCalculator,
    YearlyBillingCalculator,
)
from subscriptions.services.dates import add_months, months_between


def make_monthly(price='299.00', start=date(2026, 1, 15)):
    return Subscription(billing_type=BillingType.MONTHLY, price=Decimal(price), start_date=start)


def make_yearly(price='8900.00', start=date(2026, 3, 10)):
    return Subscription(billing_type=BillingType.YEARLY, price=Decimal(price), start_date=start)


def make_trial(
    price='299.00',
    start=date(2026, 9, 1),
    trial_end=date(2026, 9, 15),
    period_after=BillingPeriod.MONTHLY,
):
    return Subscription(
        billing_type=BillingType.TRIAL,
        price=Decimal(price),
        start_date=start,
        trial_end_date=trial_end,
        billing_period_after_trial=period_after,
    )


# --------------------------------------------------------------------------- #
# dates.py
# --------------------------------------------------------------------------- #


class AddMonthsTests(SimpleTestCase):
    """add_months: сдвиг даты на N месяцев с прижатием к концу короткого месяца."""

    def test_normal_shift(self):
        """Обычный случай: число месяца сохраняется."""
        self.assertEqual(add_months(date(2026, 1, 15), 1), date(2026, 2, 15))
        self.assertEqual(add_months(date(2026, 1, 15), 5), date(2026, 6, 15))

    def test_zero_months(self):
        """Сдвиг на 0 месяцев возвращает ту же дату."""
        self.assertEqual(add_months(date(2026, 5, 31), 0), date(2026, 5, 31))

    def test_31_january_clamped_to_28_february(self):
        """31 января + 1 месяц = 28 февраля в невисокосный год (в феврале нет 31-го)."""
        self.assertEqual(add_months(date(2026, 1, 31), 1), date(2026, 2, 28))

    def test_31_january_clamped_to_29_february_in_leap_year(self):
        """В високосный год 31 января + 1 месяц = 29 февраля."""
        self.assertEqual(add_months(date(2024, 1, 31), 1), date(2024, 2, 29))

    def test_leap_day_plus_year_goes_to_28_february(self):
        """29.02.2024 + 12 месяцев = 28.02.2025: в 2025 году 29 февраля нет."""
        self.assertEqual(add_months(date(2024, 2, 29), 12), date(2025, 2, 28))

    def test_leap_day_plus_four_years_keeps_29_february(self):
        """29.02.2024 + 48 месяцев = 29.02.2028: следующий високосный год."""
        self.assertEqual(add_months(date(2024, 2, 29), 48), date(2028, 2, 29))

    def test_year_rollover(self):
        """Ноябрь + 3 месяца переходит в февраль следующего года."""
        self.assertEqual(add_months(date(2026, 11, 20), 3), date(2027, 2, 20))
        self.assertEqual(add_months(date(2026, 11, 30), 3), date(2027, 2, 28))

    def test_negative_months(self):
        """Отрицательное число месяцев сдвигает дату назад, в том числе через границу года."""
        self.assertEqual(add_months(date(2026, 3, 15), -1), date(2026, 2, 15))
        self.assertEqual(add_months(date(2026, 2, 10), -3), date(2025, 11, 10))
        self.assertEqual(add_months(date(2026, 3, 31), -1), date(2026, 2, 28))


class MonthsBetweenTests(SimpleTestCase):
    """months_between: сколько полных шагов по месяцам от start не выходят за end."""

    def test_same_day(self):
        """Одна и та же дата - ноль месяцев."""
        self.assertEqual(months_between(date(2026, 1, 15), date(2026, 1, 15)), 0)

    def test_less_than_a_month_is_zero(self):
        """Неполный месяц не считается: с 15 января по 14 февраля - 0."""
        self.assertEqual(months_between(date(2026, 1, 15), date(2026, 2, 14)), 0)
        self.assertEqual(months_between(date(2026, 1, 31), date(2026, 2, 27)), 0)

    def test_exact_months(self):
        """Ровно N месяцев (то же число) - N, в том числе через границу года."""
        self.assertEqual(months_between(date(2026, 1, 15), date(2026, 2, 15)), 1)
        self.assertEqual(months_between(date(2025, 11, 15), date(2026, 2, 15)), 3)

    def test_end_of_month_clamp_counts_as_full_month(self):
        """С 31 января по 28 февраля - полный месяц: шаг прижимается к концу февраля."""
        self.assertEqual(months_between(date(2026, 1, 31), date(2026, 2, 28)), 1)
        self.assertEqual(months_between(date(2024, 1, 31), date(2024, 2, 29)), 1)

    def test_end_of_month_clamp_not_yet_reached(self):
        """С 31 января по 30 марта - только 1 месяц: шаг в марте приходится на 31-е."""
        self.assertEqual(months_between(date(2026, 1, 31), date(2026, 3, 30)), 1)
        self.assertEqual(months_between(date(2026, 1, 31), date(2026, 3, 31)), 2)

    def test_leap_day_year(self):
        """С 29.02.2024 по 28.02.2025 - 12 месяцев (прижатие к 28 февраля)."""
        self.assertEqual(months_between(date(2024, 2, 29), date(2025, 2, 28)), 12)
        self.assertEqual(months_between(date(2024, 2, 29), date(2025, 2, 27)), 11)


# --------------------------------------------------------------------------- #
# Абстрактный класс
# --------------------------------------------------------------------------- #


class BillingCalculatorAbstractTests(SimpleTestCase):
    """BillingCalculator - абстрактный класс: создать можно только полноценного наследника."""

    def test_cannot_instantiate_abstract_base(self):
        """Прямое создание BillingCalculator запрещено (TypeError от ABC)."""
        with self.assertRaises(TypeError):
            BillingCalculator(make_monthly())

    def test_periodic_base_is_still_abstract(self):
        """PeriodicBillingCalculator не реализует monthly_cost(), поэтому тоже абстрактный."""
        with self.assertRaises(TypeError):
            PeriodicBillingCalculator(make_monthly())

    def test_subclass_missing_method_cannot_be_instantiated(self):
        """Наследник, не реализовавший хотя бы один абстрактный метод, не создаётся."""

        class Incomplete(BillingCalculator):
            def calculate_next_renewal(self, today=None):
                return today

            def monthly_cost(self):
                return Decimal('0')
            # charge_dates() не реализован

        with self.assertRaises(TypeError):
            Incomplete(make_monthly())

    def test_complete_subclass_gets_shared_methods(self):
        """Наследник, реализовавший все абстрактные методы, создаётся и получает
        общие методы базового класса (yearly_cost, days_until_renewal, expected_amount)."""

        class Weekly(BillingCalculator):
            def calculate_next_renewal(self, today=None):
                return date(2026, 1, 8)

            def monthly_cost(self):
                return Decimal('100.00')

            def charge_dates(self, start, end):
                return [date(2026, 1, 1), date(2026, 1, 8)]

        calc = Weekly(make_monthly(price='25.00'))
        self.assertEqual(calc.yearly_cost(), Decimal('1200.00'))
        self.assertEqual(calc.days_until_renewal(today=date(2026, 1, 5)), 3)
        self.assertEqual(calc.expected_amount(date(2026, 1, 1), date(2026, 1, 31)), Decimal('50.00'))


# --------------------------------------------------------------------------- #
# Ежемесячная подписка
# --------------------------------------------------------------------------- #


class MonthlyBillingCalculatorTests(SimpleTestCase):
    """MonthlyBillingCalculator: списание каждый месяц в число даты начала."""

    def setUp(self):
        self.sub = make_monthly(price='299.00', start=date(2026, 1, 15))
        self.calc = MonthlyBillingCalculator(self.sub)

    def test_next_renewal_before_start_is_start(self):
        """До даты начала ближайшее списание - сама дата начала."""
        self.assertEqual(self.calc.calculate_next_renewal(today=date(2025, 12, 1)), date(2026, 1, 15))

    def test_next_renewal_on_start_day(self):
        """В день начала списание происходит сегодня."""
        self.assertEqual(self.calc.calculate_next_renewal(today=date(2026, 1, 15)), date(2026, 1, 15))

    def test_next_renewal_on_charge_day_is_today(self):
        """В день очередного списания ближайшее списание - сегодня (включительно)."""
        self.assertEqual(self.calc.calculate_next_renewal(today=date(2026, 4, 15)), date(2026, 4, 15))

    def test_next_renewal_day_after_charge_is_next_month(self):
        """На следующий день после списания ближайшее - через месяц."""
        self.assertEqual(self.calc.calculate_next_renewal(today=date(2026, 4, 16)), date(2026, 5, 15))

    def test_next_renewal_across_year(self):
        """После декабрьского списания следующее - в январе следующего года."""
        self.assertEqual(self.calc.calculate_next_renewal(today=date(2026, 12, 16)), date(2027, 1, 15))

    def test_days_until_renewal(self):
        """days_until_renewal - разница в днях между сегодня и ближайшим списанием."""
        self.assertEqual(self.calc.days_until_renewal(today=date(2026, 4, 10)), 5)
        self.assertEqual(self.calc.days_until_renewal(today=date(2026, 4, 15)), 0)

    def test_anchor_31st_does_not_drift(self):
        """Подписка от 31 января: 29 февраля (2024 - високосный), затем снова 31 марта.

        Даты считаются от опорной даты, а не от предыдущего списания,
        поэтому после короткого февраля число не «уезжает» на 29-е навсегда.
        """
        calc = MonthlyBillingCalculator(make_monthly(start=date(2024, 1, 31)))
        self.assertEqual(calc.calculate_next_renewal(today=date(2024, 2, 1)), date(2024, 2, 29))
        self.assertEqual(calc.calculate_next_renewal(today=date(2024, 3, 1)), date(2024, 3, 31))
        self.assertEqual(calc.calculate_next_renewal(today=date(2024, 4, 1)), date(2024, 4, 30))
        self.assertEqual(calc.calculate_next_renewal(today=date(2024, 5, 1)), date(2024, 5, 31))

    def test_anchor_31st_non_leap_year(self):
        """В невисокосный год подписка от 31 января спишется 28 февраля, затем 31 марта."""
        calc = MonthlyBillingCalculator(make_monthly(start=date(2026, 1, 31)))
        self.assertEqual(
            calc.charge_dates(date(2026, 1, 1), date(2026, 4, 30)),
            [date(2026, 1, 31), date(2026, 2, 28), date(2026, 3, 31), date(2026, 4, 30)],
        )

    def test_monthly_cost_is_price(self):
        """Стоимость в месяц для ежемесячной подписки - её цена."""
        self.assertEqual(self.calc.monthly_cost(), Decimal('299.00'))

    def test_yearly_cost_is_price_times_12(self):
        """Годовой эквивалент ежемесячной подписки - цена × 12."""
        self.assertEqual(self.calc.yearly_cost(), Decimal('3588.00'))

    def test_charge_dates_half_year(self):
        """За полугодие - шесть списаний, каждое 15-го числа."""
        self.assertEqual(
            self.calc.charge_dates(date(2026, 1, 1), date(2026, 6, 30)),
            [date(2026, m, 15) for m in range(1, 7)],
        )

    def test_charge_dates_bounds_inclusive(self):
        """Границы интервала включаются: списания в start и end попадают в список."""
        self.assertEqual(
            self.calc.charge_dates(date(2026, 2, 15), date(2026, 3, 15)),
            [date(2026, 2, 15), date(2026, 3, 15)],
        )

    def test_charge_dates_range_without_charges(self):
        """Интервал между двумя списаниями - пустой список."""
        self.assertEqual(self.calc.charge_dates(date(2026, 2, 16), date(2026, 3, 14)), [])

    def test_charge_dates_inverted_range(self):
        """Если start позже end, списаний нет."""
        self.assertEqual(self.calc.charge_dates(date(2026, 6, 30), date(2026, 1, 1)), [])

    def test_charge_dates_range_before_start(self):
        """Интервал целиком до даты начала подписки - пустой список."""
        self.assertEqual(self.calc.charge_dates(date(2025, 1, 1), date(2025, 12, 31)), [])

    def test_expected_amount(self):
        """Прогноз за интервал - цена × количество списаний: за полугодие 299 × 6."""
        self.assertEqual(
            self.calc.expected_amount(date(2026, 1, 1), date(2026, 6, 30)),
            Decimal('1794.00'),
        )
        self.assertEqual(self.calc.expected_amount(date(2026, 2, 16), date(2026, 3, 14)), Decimal('0.00'))


# --------------------------------------------------------------------------- #
# Ежегодная подписка
# --------------------------------------------------------------------------- #


class YearlyBillingCalculatorTests(SimpleTestCase):
    """YearlyBillingCalculator: списание раз в 12 месяцев от даты начала."""

    def setUp(self):
        self.sub = make_yearly(price='8900.00', start=date(2026, 3, 10))
        self.calc = YearlyBillingCalculator(self.sub)

    def test_next_renewal_before_start(self):
        """До начала подписки ближайшее списание - дата начала."""
        self.assertEqual(self.calc.calculate_next_renewal(today=date(2026, 1, 1)), date(2026, 3, 10))

    def test_next_renewal_within_first_year(self):
        """Внутри первого года ближайшее списание - через год после начала."""
        self.assertEqual(self.calc.calculate_next_renewal(today=date(2026, 3, 11)), date(2027, 3, 10))
        self.assertEqual(self.calc.calculate_next_renewal(today=date(2027, 1, 1)), date(2027, 3, 10))

    def test_next_renewal_on_anniversary(self):
        """В годовщину списание происходит сегодня."""
        self.assertEqual(self.calc.calculate_next_renewal(today=date(2028, 3, 10)), date(2028, 3, 10))

    def test_next_renewal_several_years_later(self):
        """Спустя несколько лет - ближайшая следующая годовщина."""
        self.assertEqual(self.calc.calculate_next_renewal(today=date(2029, 7, 1)), date(2030, 3, 10))

    def test_leap_day_anchor(self):
        """Подписка от 29.02.2024: в невисокосные годы 28 февраля, в 2028 - снова 29-го."""
        calc = YearlyBillingCalculator(make_yearly(start=date(2024, 2, 29)))
        self.assertEqual(calc.calculate_next_renewal(today=date(2024, 3, 1)), date(2025, 2, 28))
        self.assertEqual(calc.calculate_next_renewal(today=date(2025, 3, 1)), date(2026, 2, 28))
        self.assertEqual(calc.calculate_next_renewal(today=date(2027, 3, 1)), date(2028, 2, 29))
        self.assertEqual(
            calc.charge_dates(date(2024, 1, 1), date(2028, 12, 31)),
            [date(2024, 2, 29), date(2025, 2, 28), date(2026, 2, 28), date(2027, 2, 28), date(2028, 2, 29)],
        )

    def test_monthly_cost_is_price_div_12_rounded_to_kopecks(self):
        """Стоимость в месяц - цена / 12, округлённая до копеек (ROUND_HALF_UP): 8900 / 12 = 741.67."""
        self.assertEqual(self.calc.monthly_cost(), Decimal('741.67'))

    def test_yearly_cost_overridden_with_exact_price(self):
        """Годовой эквивалент ежегодной подписки равен её цене, а не monthly_cost() × 12.

        Базовый класс считает yearly_cost() как monthly_cost() × 12. Для ежегодной
        подписки это дало бы 741.67 × 12 = 8900.04 из-за округления месячной цены,
        поэтому YearlyBillingCalculator переопределяет метод (полиморфизм через
        переопределение) и возвращает точную годовую цену.
        """
        self.assertEqual(self.calc.monthly_cost(), Decimal('741.67'))
        self.assertEqual(self.calc.yearly_cost(), Decimal('8900.00'))

    def test_yearly_cost_exact_when_price_divisible(self):
        """Если цена делится на 12 без остатка до копеек, годовой эквивалент равен цене."""
        calc = YearlyBillingCalculator(make_yearly(price='1200.00'))
        self.assertEqual(calc.monthly_cost(), Decimal('100.00'))
        self.assertEqual(calc.yearly_cost(), Decimal('1200.00'))

    def test_charge_dates_one_per_year(self):
        """За три года - три списания, по одному в годовщину."""
        self.assertEqual(
            self.calc.charge_dates(date(2026, 1, 1), date(2028, 12, 31)),
            [date(2026, 3, 10), date(2027, 3, 10), date(2028, 3, 10)],
        )

    def test_charge_dates_empty_between_anniversaries(self):
        """Интервал внутри года между годовщинами - списаний нет."""
        self.assertEqual(self.calc.charge_dates(date(2026, 4, 1), date(2027, 3, 9)), [])

    def test_expected_amount_uses_full_price_per_charge(self):
        """Прогноз для ежегодной подписки - полная цена за каждую годовщину в интервале."""
        self.assertEqual(self.calc.expected_amount(date(2026, 3, 1), date(2026, 3, 31)), Decimal('8900.00'))
        self.assertEqual(self.calc.expected_amount(date(2026, 4, 1), date(2026, 4, 30)), Decimal('0.00'))


# --------------------------------------------------------------------------- #
# Пробный период
# --------------------------------------------------------------------------- #


class TrialBillingCalculatorTests(SimpleTestCase):
    """TrialBillingCalculator: бесплатно до trial_end_date, затем периодическая оплата."""

    def setUp(self):
        self.sub = make_trial(price='299.00', start=date(2026, 9, 1), trial_end=date(2026, 9, 15))
        self.calc = TrialBillingCalculator(self.sub)

    def test_trial_active_before_end_date(self):
        """До даты окончания пробный период активен."""
        self.assertTrue(self.calc.is_trial_active(today=date(2026, 9, 1)))
        self.assertTrue(self.calc.is_trial_active(today=date(2026, 9, 14)))

    def test_trial_not_active_on_end_date(self):
        """В день окончания пробный период уже не активен: в этот день первое списание."""
        self.assertFalse(self.calc.is_trial_active(today=date(2026, 9, 15)))

    def test_trial_not_active_after_end_date(self):
        """После даты окончания пробный период не активен."""
        self.assertFalse(self.calc.is_trial_active(today=date(2026, 10, 1)))

    def test_days_until_trial_end(self):
        """Сколько дней осталось до конца триала; после окончания - отрицательное число."""
        self.assertEqual(self.calc.days_until_trial_end(today=date(2026, 9, 12)), 3)
        self.assertEqual(self.calc.days_until_trial_end(today=date(2026, 9, 15)), 0)
        self.assertEqual(self.calc.days_until_trial_end(today=date(2026, 9, 17)), -2)

    def test_after_trial_calculator_is_delegate(self):
        """Поведение после триала делегируется периодическому калькулятору (композиция)
        с опорной датой = дата окончания триала."""
        self.assertIsInstance(self.calc.after_trial, MonthlyBillingCalculator)
        self.assertEqual(self.calc.after_trial.anchor, date(2026, 9, 15))

    def test_next_renewal_during_trial_is_trial_end(self):
        """Во время триала ближайшее списание - дата его окончания."""
        self.assertEqual(self.calc.calculate_next_renewal(today=date(2026, 9, 3)), date(2026, 9, 15))
        self.assertEqual(self.calc.calculate_next_renewal(today=date(2026, 9, 15)), date(2026, 9, 15))

    def test_next_renewal_after_trial_monthly(self):
        """После триала с помесячной оплатой - шаг в месяц от даты окончания триала."""
        self.assertEqual(self.calc.calculate_next_renewal(today=date(2026, 9, 16)), date(2026, 10, 15))
        self.assertEqual(self.calc.calculate_next_renewal(today=date(2027, 1, 20)), date(2027, 2, 15))

    def test_next_renewal_after_trial_yearly(self):
        """После триала с годовой оплатой - шаг в год от даты окончания триала."""
        calc = TrialBillingCalculator(make_trial(price='3000.00', period_after=BillingPeriod.YEARLY))
        self.assertIsInstance(calc.after_trial, YearlyBillingCalculator)
        self.assertEqual(calc.calculate_next_renewal(today=date(2026, 9, 10)), date(2026, 9, 15))
        self.assertEqual(calc.calculate_next_renewal(today=date(2026, 9, 16)), date(2027, 9, 15))

    def test_monthly_cost_uses_after_trial_period_monthly(self):
        """Стоимость в месяц считается по цене после триала, даже пока триал идёт:
        это расход, который начнётся, если не отменить подписку."""
        self.assertEqual(self.calc.monthly_cost(), Decimal('299.00'))
        self.assertEqual(self.calc.yearly_cost(), Decimal('3588.00'))

    def test_monthly_cost_uses_after_trial_period_yearly(self):
        """Если после триала оплата раз в год, стоимость в месяц - цена / 12,
        а годовой эквивалент делегируется годовому калькулятору и равен цене."""
        calc = TrialBillingCalculator(make_trial(price='2999.00', period_after=BillingPeriod.YEARLY))
        self.assertEqual(calc.monthly_cost(), Decimal('249.92'))
        self.assertEqual(calc.yearly_cost(), Decimal('2999.00'))

    def test_charge_dates_start_from_trial_end(self):
        """Списаний до конца триала нет; первое - в день окончания триала."""
        self.assertEqual(
            self.calc.charge_dates(date(2026, 9, 1), date(2026, 12, 31)),
            [date(2026, 9, 15), date(2026, 10, 15), date(2026, 11, 15), date(2026, 12, 15)],
        )
        self.assertEqual(self.calc.charge_dates(date(2026, 9, 1), date(2026, 9, 14)), [])

    def test_expected_amount_during_trial_month(self):
        """Прогноз за сентябрь: одно списание в день окончания триала."""
        self.assertEqual(self.calc.expected_amount(date(2026, 9, 1), date(2026, 9, 30)), Decimal('299.00'))


# --------------------------------------------------------------------------- #
# Фабрика и полиморфизм
# --------------------------------------------------------------------------- #


class BillingCalculatorFactoryTests(SimpleTestCase):
    """BillingCalculatorFactory выбирает класс калькулятора по billing_type."""

    def test_monthly_type(self):
        """billing_type=monthly → MonthlyBillingCalculator."""
        calc = BillingCalculatorFactory.create(make_monthly())
        self.assertIs(type(calc), MonthlyBillingCalculator)

    def test_yearly_type(self):
        """billing_type=yearly → YearlyBillingCalculator."""
        calc = BillingCalculatorFactory.create(make_yearly())
        self.assertIs(type(calc), YearlyBillingCalculator)

    def test_trial_type(self):
        """billing_type=trial → TrialBillingCalculator."""
        calc = BillingCalculatorFactory.create(make_trial())
        self.assertIs(type(calc), TrialBillingCalculator)

    def test_calculator_keeps_subscription(self):
        """Калькулятор хранит ссылку на ту же подписку, которую ему передали."""
        sub = make_monthly()
        self.assertIs(BillingCalculatorFactory.create(sub).subscription, sub)

    def test_unknown_type_raises_value_error(self):
        """Неизвестный тип оплаты → ValueError с понятным сообщением."""
        sub = make_monthly()
        sub.billing_type = 'weekly'
        with self.assertRaisesMessage(ValueError, "Неизвестный тип оплаты: 'weekly'"):
            BillingCalculatorFactory.create(sub)

    def test_all_calculators_share_base_class(self):
        """Любой калькулятор из фабрики - экземпляр абстрактного BillingCalculator."""
        for sub in (make_monthly(), make_yearly(), make_trial()):
            with self.subTest(billing_type=sub.billing_type):
                self.assertIsInstance(BillingCalculatorFactory.create(sub), BillingCalculator)

    def test_polymorphic_monthly_total(self):
        """Полиморфизм: сумма расходов в месяц по смешанному списку подписок считается
        одним вызовом monthly_cost() - без isinstance и без проверок billing_type.

        299.00 (месяц) + 741.67 (8900 в год) + 199.00 (триал → месяц) + 250.00 (триал → 3000 в год)
        = 1489.67
        """
        subscriptions = [
            make_monthly(price='299.00'),
            make_yearly(price='8900.00'),
            make_trial(price='199.00', period_after=BillingPeriod.MONTHLY),
            make_trial(price='3000.00', period_after=BillingPeriod.YEARLY),
        ]
        total = sum(
            (BillingCalculatorFactory.create(sub).monthly_cost() for sub in subscriptions),
            Decimal('0'),
        )
        self.assertEqual(total, Decimal('1489.67'))

    def test_polymorphic_next_renewals(self):
        """Полиморфизм: ближайшие продления разных подписок - один и тот же вызов."""
        today = date(2026, 9, 10)
        subscriptions = [
            make_monthly(start=date(2026, 1, 15)),
            make_yearly(start=date(2026, 3, 10)),
            make_trial(trial_end=date(2026, 9, 15)),
        ]
        renewals = [BillingCalculatorFactory.create(s).calculate_next_renewal(today) for s in subscriptions]
        self.assertEqual(renewals, [date(2026, 9, 15), date(2027, 3, 10), date(2026, 9, 15)])


# --------------------------------------------------------------------------- #
# Граничные случаи
# --------------------------------------------------------------------------- #


class BillingEdgeCaseTests(SimpleTestCase):
    """Граничные случаи: нулевая цена и точность Decimal."""

    def test_zero_price(self):
        """Бесплатная подписка (цена 0) - все суммы нулевые, даты списаний считаются как обычно."""
        for sub in (make_monthly(price='0'), make_yearly(price='0'), make_trial(price='0')):
            with self.subTest(billing_type=sub.billing_type):
                calc = BillingCalculatorFactory.create(sub)
                self.assertEqual(calc.monthly_cost(), Decimal('0.00'))
                self.assertEqual(calc.yearly_cost(), Decimal('0.00'))
                self.assertEqual(calc.expected_amount(date(2026, 1, 1), date(2027, 12, 31)), Decimal('0.00'))

        calc = MonthlyBillingCalculator(make_monthly(price='0'))
        self.assertEqual(len(calc.charge_dates(date(2026, 1, 1), date(2026, 12, 31))), 12)

    def test_results_are_decimal_not_float(self):
        """Все денежные результаты - Decimal с двумя знаками после запятой, float не используется."""
        for sub in (make_monthly(price='199.99'), make_yearly(price='999.99'), make_trial(price='149.50')):
            with self.subTest(billing_type=sub.billing_type):
                calc = BillingCalculatorFactory.create(sub)
                values = [
                    calc.monthly_cost(),
                    calc.yearly_cost(),
                    calc.expected_amount(date(2026, 1, 1), date(2027, 12, 31)),
                ]
                for value in values:
                    self.assertIsInstance(value, Decimal)
                    self.assertEqual(value.as_tuple().exponent, -2)

    def test_decimal_precision_preserved(self):
        """Копейки не теряются: 199.99 × 12 = 2399.88 ровно (во float было бы 2399.8799999…)."""
        calc = MonthlyBillingCalculator(make_monthly(price='199.99'))
        self.assertEqual(calc.yearly_cost(), Decimal('2399.88'))
        self.assertEqual(
            calc.expected_amount(date(2026, 1, 1), date(2026, 3, 31)),
            Decimal('599.97'),
        )

    def test_yearly_rounding_half_up(self):
        """Округление до копеек - по правилу ROUND_HALF_UP: 100.02 / 12 = 8.335 → 8.34."""
        calc = YearlyBillingCalculator(make_yearly(price='100.02'))
        self.assertEqual(calc.monthly_cost(), Decimal('8.34'))
