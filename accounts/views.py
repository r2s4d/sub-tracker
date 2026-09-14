from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.auth.views import LoginView
from django.contrib.messages.views import SuccessMessageMixin
from django.shortcuts import redirect
from django.urls import reverse_lazy
from django.views.generic import CreateView, UpdateView

from .forms import LoginForm, ProfileForm, SignUpForm


class SignInView(LoginView):
    form_class = LoginForm
    redirect_authenticated_user = True


class SignUpView(CreateView):
    form_class = SignUpForm
    template_name = 'accounts/signup.html'

    def dispatch(self, request, *args, **kwargs):
        if request.user.is_authenticated:
            return redirect('home')
        return super().dispatch(request, *args, **kwargs)

    def form_valid(self, form):
        user = form.save()
        # Сразу входим, чтобы после регистрации не просить пароль второй раз.
        login(self.request, user)
        messages.success(self.request, 'Аккаунт создан. Добавьте первую подписку.')
        return redirect('home')


class ProfileView(LoginRequiredMixin, SuccessMessageMixin, UpdateView):
    """Редактирует профиль только текущего пользователя: pk в URL нет вовсе."""

    form_class = ProfileForm
    template_name = 'accounts/profile.html'
    success_url = reverse_lazy('profile')
    success_message = 'Настройки сохранены.'

    def get_object(self, queryset=None):
        return self.request.user.profile
