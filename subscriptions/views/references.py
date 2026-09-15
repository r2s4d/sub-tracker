"""Справочники пользователя: способы оплаты, теги и свои сервисы.

Изоляция — через OwnedQuerysetMixin (чужой pk → 404), владелец новой
записи назначается во view, а не берётся из POST.
"""

from django.contrib import messages
from django.contrib.messages.views import SuccessMessageMixin
from django.db.models import Count, ProtectedError
from django.shortcuts import redirect
from django.urls import reverse_lazy
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.generic import CreateView, DeleteView, ListView, UpdateView

from ..forms.references import PaymentMethodForm, ServiceForm, TagForm
from ..mixins import OwnedQuerysetMixin, OwnerFormMixin
from ..models import PaymentMethod, Service, Tag


def subscriptions_in(n):
    """«в 1 подписке», «в 5 подписках» — предложный падеж, две формы."""
    word = 'подписке' if n % 10 == 1 and n % 100 != 11 else 'подписках'
    return f'в {n} {word}'


def subscriptions_count(n):
    """«1 подписка», «3 подписки», «5 подписок»."""
    if n % 10 == 1 and n % 100 != 11:
        word = 'подписка'
    elif 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14:
        word = 'подписки'
    else:
        word = 'подписок'
    return f'{n} {word}'


class SafeNextMixin:
    """После создания возвращает на ?next=, если это адрес этого же сайта.

    Нужен форме подписки: пользователь уходит добавить карту или сервис
    и возвращается обратно. Внешние адреса игнорируются (open redirect).
    """

    def get_next_url(self):
        url = self.request.POST.get('next') or self.request.GET.get('next')
        if url and url_has_allowed_host_and_scheme(
            url,
            allowed_hosts={self.request.get_host()},
            require_https=self.request.is_secure(),
        ):
            return url
        return None

    def get_success_url(self):
        return self.get_next_url() or super().get_success_url()

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['next_url'] = self.get_next_url()
        context['cancel_url'] = context['next_url'] or self.success_url
        return context


class CancelUrlMixin:
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.setdefault('cancel_url', self.success_url)
        return context


# ---------- Способы оплаты ----------

class PaymentMethodListView(OwnedQuerysetMixin, ListView):
    model = PaymentMethod
    context_object_name = 'payment_methods'

    def get_queryset(self):
        return super().get_queryset().annotate(subscription_count=Count('subscriptions'))

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        for method in context['payment_methods']:
            method.usage_label = subscriptions_count(method.subscription_count)
        return context


class PaymentMethodCreateView(OwnerFormMixin, SuccessMessageMixin, SafeNextMixin, CreateView):
    model = PaymentMethod
    form_class = PaymentMethodForm
    success_url = reverse_lazy('subscriptions:paymentmethod-list')
    success_message = 'Способ оплаты добавлен.'


class PaymentMethodUpdateView(OwnedQuerysetMixin, OwnerFormMixin, SuccessMessageMixin, CancelUrlMixin, UpdateView):
    model = PaymentMethod
    form_class = PaymentMethodForm
    success_url = reverse_lazy('subscriptions:paymentmethod-list')
    success_message = 'Способ оплаты сохранён.'


class PaymentMethodDeleteView(OwnedQuerysetMixin, SuccessMessageMixin, CancelUrlMixin, DeleteView):
    model = PaymentMethod
    template_name = 'partials/confirm_delete.html'
    success_url = reverse_lazy('subscriptions:paymentmethod-list')
    success_message = 'Способ оплаты удалён.'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['delete_title'] = 'Удалить способ оплаты?'
        context['delete_warning'] = (
            'Подписки и история платежей останутся — у них просто не будет указан способ оплаты.'
        )
        return context


# ---------- Теги ----------

class TagListView(OwnedQuerysetMixin, ListView):
    model = Tag
    context_object_name = 'tags'

    def get_queryset(self):
        return super().get_queryset().annotate(subscription_count=Count('subscriptions'))

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        for tag in context['tags']:
            tag.usage_label = subscriptions_count(tag.subscription_count)
        return context


class TagCreateView(OwnerFormMixin, SuccessMessageMixin, SafeNextMixin, CreateView):
    model = Tag
    form_class = TagForm
    success_url = reverse_lazy('subscriptions:tag-list')
    success_message = 'Тег добавлен.'


class TagUpdateView(OwnedQuerysetMixin, OwnerFormMixin, SuccessMessageMixin, CancelUrlMixin, UpdateView):
    model = Tag
    form_class = TagForm
    success_url = reverse_lazy('subscriptions:tag-list')
    success_message = 'Тег сохранён.'


class TagDeleteView(OwnedQuerysetMixin, SuccessMessageMixin, CancelUrlMixin, DeleteView):
    model = Tag
    template_name = 'partials/confirm_delete.html'
    success_url = reverse_lazy('subscriptions:tag-list')
    success_message = 'Тег удалён.'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        count = self.object.subscriptions.count()
        context['delete_title'] = 'Удалить тег?'
        if count:
            context['delete_warning'] = (
                f'Тег стоит {subscriptions_in(count)}. Он будет снят с них, сами подписки останутся.'
            )
        else:
            context['delete_warning'] = 'Тег не используется ни в одной подписке.'
        return context


# ---------- Сервисы ----------

class ServiceOwnerFormMixin(OwnerFormMixin):
    """У Service владелец хранится в поле owner, а не user."""

    def form_valid(self, form):
        form.instance.owner = self.request.user
        # Пропускаем OwnerFormMixin.form_valid: он проставил бы несуществующее поле user.
        return super(OwnerFormMixin, self).form_valid(form)


class ServiceListView(OwnedQuerysetMixin, ListView):
    """Свои сервисы (редактируются) и общий каталог (только просмотр)."""

    model = Service
    owner_field = 'owner'
    context_object_name = 'own_services'

    def get_search(self):
        return self.request.GET.get('q', '').strip()

    def get_queryset(self):
        qs = (
            super().get_queryset()
            .select_related('category')
            .annotate(subscription_count=Count('subscriptions'))
        )
        if q := self.get_search():
            qs = qs.filter(name__icontains=q)
        return qs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        for service in context['own_services']:
            service.usage_label = subscriptions_count(service.subscription_count)

        catalog = (
            Service.objects.filter(owner__isnull=True)
            .select_related('category')
            .order_by('category__sort_order', 'category__name', 'name')
        )
        if q := self.get_search():
            catalog = catalog.filter(name__icontains=q)
        context['catalog'] = catalog
        context['q'] = self.get_search()
        return context


class ServiceCreateView(ServiceOwnerFormMixin, SuccessMessageMixin, SafeNextMixin, CreateView):
    model = Service
    form_class = ServiceForm
    success_url = reverse_lazy('subscriptions:service-list')
    success_message = 'Сервис добавлен.'


class ServiceUpdateView(OwnedQuerysetMixin, ServiceOwnerFormMixin, SuccessMessageMixin, CancelUrlMixin, UpdateView):
    model = Service
    owner_field = 'owner'  # сервисы каталога (owner = NULL) сюда не попадают → 404
    form_class = ServiceForm
    success_url = reverse_lazy('subscriptions:service-list')
    success_message = 'Сервис сохранён.'


class ServiceDeleteView(OwnedQuerysetMixin, SuccessMessageMixin, CancelUrlMixin, DeleteView):
    model = Service
    owner_field = 'owner'
    success_url = reverse_lazy('subscriptions:service-list')
    success_message = 'Сервис удалён.'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        count = self.object.subscriptions.count()
        context['subscription_count'] = count
        context['usage_label'] = subscriptions_in(count)
        return context

    def form_valid(self, form):
        # Subscription.service — PROTECT: удалить используемый сервис БД не даст.
        try:
            return super().form_valid(form)
        except ProtectedError:
            count = self.object.subscriptions.count()
            messages.error(
                self.request,
                f'Нельзя удалить: сервис используется {subscriptions_in(count)}.',
            )
            return redirect(self.success_url)
