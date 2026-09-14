import calendar
from datetime import date


def add_months(day: date, months: int) -> date:
    """Сдвигает дату на N месяцев, прижимая число к концу короткого месяца.

    31.01 + 1 месяц = 28.02 (или 29.02 в високосный год).
    """
    month_index = day.month - 1 + months
    year, month = day.year + month_index // 12, month_index % 12 + 1
    return date(year, month, min(day.day, calendar.monthrange(year, month)[1]))


def months_between(start: date, end: date) -> int:
    """Сколько полных календарных «шагов по месяцам» от start не превышают end."""
    months = (end.year - start.year) * 12 + (end.month - start.month)
    if add_months(start, months) > end:
        months -= 1
    return months
