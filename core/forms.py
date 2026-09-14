from django import forms


class BootstrapFormMixin:
    """Проставляет виджетам формы CSS-классы Bootstrap.

    Миксин вместо стороннего пакета (django-crispy-forms и т.п.): логика —
    десяток строк, а зависимостей меньше.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            widget = field.widget
            if isinstance(widget, (forms.CheckboxInput,)):
                css = 'form-check-input'
            elif isinstance(widget, forms.CheckboxSelectMultiple):
                css = ''
            elif isinstance(widget, (forms.Select, forms.SelectMultiple)):
                css = 'form-select'
            else:
                css = 'form-control'
            if css:
                widget.attrs['class'] = f"{widget.attrs.get('class', '')} {css}".strip()

    def is_valid(self):
        valid = super().is_valid()
        for name in self.errors:
            if name in self.fields:
                widget = self.fields[name].widget
                widget.attrs['class'] = f"{widget.attrs.get('class', '')} is-invalid".strip()
        return valid


class DateInput(forms.DateInput):
    """Нативный календарь браузера (<input type="date">)."""

    input_type = 'date'

    def __init__(self, attrs=None):
        super().__init__(attrs=attrs, format='%Y-%m-%d')
