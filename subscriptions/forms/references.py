from django import forms

from core.forms import BootstrapFormMixin

from ..models import PaymentMethod, Service, Tag


class PaymentMethodForm(BootstrapFormMixin, forms.ModelForm):
    class Meta:
        model = PaymentMethod
        fields = ['name', 'kind', 'last4']
        widgets = {
            'last4': forms.TextInput(attrs={
                'inputmode': 'numeric',
                'maxlength': 4,
                'autocomplete': 'off',
                'placeholder': '1234',
            }),
        }
        help_texts = {
            'last4': 'Чтобы отличать карты одного банка. Полный номер не нужен.',
        }

    def __init__(self, *args, user=None, **kwargs):
        self.user = user
        super().__init__(*args, **kwargs)

    def clean_last4(self):
        last4 = self.cleaned_data['last4'].strip()
        if last4 and not (len(last4) == 4 and last4.isascii() and last4.isdigit()):
            raise forms.ValidationError('Введите ровно 4 цифры.')
        return last4


class TagForm(BootstrapFormMixin, forms.ModelForm):
    class Meta:
        model = Tag
        fields = ['name']
        help_texts = {
            'name': 'Например, «семья», «работа» или «можно отменить».',
        }

    def __init__(self, *args, user=None, **kwargs):
        self.user = user
        super().__init__(*args, **kwargs)

    def clean_name(self):
        name = self.cleaned_data['name'].strip()
        # user не поле формы, поэтому UniqueConstraint(user, name) ModelForm не проверит -
        # без этой проверки дубль упал бы IntegrityError.
        duplicates = Tag.objects.filter(user=self.user, name__iexact=name)
        if self.instance.pk:
            duplicates = duplicates.exclude(pk=self.instance.pk)
        if duplicates.exists():
            raise forms.ValidationError('У вас уже есть тег с таким названием.')
        return name


class ServiceForm(BootstrapFormMixin, forms.ModelForm):
    class Meta:
        model = Service
        fields = ['name', 'category', 'website']
        widgets = {
            'website': forms.URLInput(attrs={'placeholder': 'https://'}),
        }

    def __init__(self, *args, user=None, **kwargs):
        self.user = user
        super().__init__(*args, **kwargs)
        self.fields['category'].empty_label = 'Выберите категорию'

    def clean_name(self):
        name = self.cleaned_data['name'].strip()
        own = Service.objects.filter(owner=self.user, name__iexact=name)
        if self.instance.pk:
            own = own.exclude(pk=self.instance.pk)
        if own.exists():
            raise forms.ValidationError('У вас уже есть сервис с таким названием.')
        if Service.objects.filter(owner__isnull=True, name__iexact=name).exists():
            raise forms.ValidationError(
                'Такой сервис уже есть в каталоге. Выберите его при добавлении подписки.'
            )
        return name
