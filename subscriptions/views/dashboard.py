from django.contrib.auth.mixins import LoginRequiredMixin
from django.utils import timezone
from django.views.generic import TemplateView

from subscriptions.services.analytics import build_dashboard


class DashboardView(LoginRequiredMixin, TemplateView):
    """Обзор расходов. Вся логика - в services.analytics, view только собирает контекст.

    Данные строятся строго по request.user: чужие подписки в выборки не попадают.
    """

    template_name = 'subscriptions/dashboard.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['dashboard'] = build_dashboard(self.request.user, timezone.localdate())
        return context
