from django import template

from subscriptions.services.notifications import days_left_phrase

register = template.Library()


@register.filter
def plural_ru(number, forms):
    """{{ n|plural_ru:'подписка,подписки,подписок' }} → форма слова для числа n."""
    one, few, many = forms.split(',')
    n = abs(int(number))
    if n % 10 == 1 and n % 100 != 11:
        return one
    if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14:
        return few
    return many


@register.filter
def days_left(days):
    """0 → «сегодня», 1 → «завтра», 3 → «через 3 дня»."""
    return days_left_phrase(int(days))
