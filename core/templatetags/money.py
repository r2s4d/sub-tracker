from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from django import template
from django.utils.html import format_html

register = template.Library()

NBSP_THIN = ' '  # узкий неразрывный пробел — разделитель разрядов в русской типографике


def _split(value):
    try:
        amount = Decimal(value).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
    except (InvalidOperation, TypeError, ValueError):
        return None
    sign = '−' if amount < 0 else ''
    rubles, kopecks = f'{abs(amount):.2f}'.split('.')
    rubles = f'{int(rubles):,}'.replace(',', NBSP_THIN)
    return sign, rubles, kopecks


@register.filter
def rub(value):
    """1299.5 → «1 299,50 ₽» (простой текст, для атрибутов и подсказок)."""
    parts = _split(value)
    if parts is None:
        return ''
    sign, rubles, kopecks = parts
    return f'{sign}{rubles},{kopecks} ₽'


@register.filter
def rub_html(value):
    """Сумма с уменьшенными копейками: главный типографический акцент интерфейса."""
    parts = _split(value)
    if parts is None:
        return ''
    sign, rubles, kopecks = parts
    return format_html(
        '<span class="money">{}{}<span class="money-kop">,{}</span><span class="money-cur"> ₽</span></span>',
        sign, rubles, kopecks,
    )
