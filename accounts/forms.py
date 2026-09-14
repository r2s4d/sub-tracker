from django import forms
from django.contrib.auth.forms import AuthenticationForm, UserCreationForm
from django.contrib.auth.models import User

from core.forms import BootstrapFormMixin

from .models import UserProfile


class LoginForm(BootstrapFormMixin, AuthenticationForm):
    pass


class SignUpForm(BootstrapFormMixin, UserCreationForm):
    email = forms.EmailField(
        label='Почта',
        help_text='На неё придёт напоминание об окончании пробного периода.',
    )

    class Meta(UserCreationForm.Meta):
        model = User
        fields = ('username', 'email')

    def clean_email(self):
        email = self.cleaned_data['email'].lower()
        if User.objects.filter(email__iexact=email).exists():
            raise forms.ValidationError('Аккаунт с этой почтой уже есть.')
        return email


class ProfileForm(BootstrapFormMixin, forms.ModelForm):
    class Meta:
        model = UserProfile
        fields = ('notification_email', 'notify_days_before', 'monthly_budget')
        widgets = {
            'notify_days_before': forms.NumberInput(attrs={'min': 0, 'max': 60}),
            'monthly_budget': forms.NumberInput(attrs={'min': 0, 'step': '0.01'}),
        }
