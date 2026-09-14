from django.contrib import messages
from django.contrib.messages.views import SuccessMessageMixin
from django.db.models import Sum
from django.shortcuts import redirect
from django.urls import reverse, reverse_lazy
from django.utils import timezone
from django.views import View
from django.views.generic import CreateView, DeleteView, DetailView, ListView, UpdateView
from django.views.generic.detail import SingleObjectMixin

from core.templatetags.money import rub
from subscriptions.forms.subscriptions import PaymentForm, SubscriptionForm
from subscriptions.mixins import OwnedQuerysetMixin, OwnerFormMixin
from subscriptions.models import BillingType, Category, Payment, Subscription

STATUS_CHOICES = [
    ('active', 'Активные'),
    ('inactive', 'Отключённые'),
    ('all', 'Все'),
]


def plural_ru(n, one, few, many):
    """1 подписка, 2 подписки, 5 подписок."""
    if n % 10 == 1 and n % 100 != 11:
        return one
    if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14:
        return few
    return many


class SubscriptionListView(OwnedQuerysetMixin, ListView):
    model = Subscription
    template_name = 'subscriptions/subscription_list.html'
    context_object_name = 'subscriptions'

    def get_filters(self):
        """Читает фильтры из GET; неизвестные значения молча игнорируются."""
        params = self.request.GET
        billing_type = params.get('billing_type', '')
        status = params.get('status', 'active')
        tag = params.get('tag', '')
        return {
            'category': params.get('category', ''),
            'billing_type': billing_type if billing_type in BillingType.values else '',
            'status': status if status in dict(STATUS_CHOICES) else 'active',
            'tag': tag if tag.isdigit() else '',
        }

    def get_queryset(self):
        # Сначала OwnedQuerysetMixin оставляет только свои подписки, затем фильтры.
        qs = super().get_queryset().select_related('service__category', 'payment_method').prefetch_related('tags')
        f = self.filters = self.get_filters()
        if f['category']:
            qs = qs.filter(service__category__slug=f['category'])
        if f['billing_type']:
            qs = qs.filter(billing_type=f['billing_type'])
        if f['status'] == 'active':
            qs = qs.filter(is_active=True)
        elif f['status'] == 'inactive':
            qs = qs.filter(is_active=False)
        if f['tag']:
            qs = qs.filter(tags__id=f['tag'])
        return qs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        f = self.filters
        count = len(context['subscriptions'])
        is_filtered = bool(f['category'] or f['billing_type'] or f['tag'] or f['status'] != 'active')
        context.update(
            filters=f,
            is_filtered=is_filtered,
            categories=Category.objects.all(),
            tags=self.request.user.tags.all(),
            billing_choices=BillingType.choices,
            status_choices=STATUS_CHOICES,
            count_label=f"{count} {plural_ru(count, 'подписка', 'подписки', 'подписок')}",
        )
        if not count:
            # Нужно, чтобы отличить «ещё ничего не добавлено» от «фильтр ничего не нашёл».
            context['has_any'] = self.request.user.subscriptions.exists()
        return context


class SubscriptionCreateView(OwnerFormMixin, SuccessMessageMixin, CreateView):
    model = Subscription
    form_class = SubscriptionForm
    template_name = 'subscriptions/subscription_form.html'
    success_message = 'Подписка добавлена'

    def get_success_url(self):
        return reverse('subscriptions:detail', args=[self.object.pk])


class SubscriptionDetailView(OwnedQuerysetMixin, DetailView):
    model = Subscription
    template_name = 'subscriptions/subscription_detail.html'
    context_object_name = 'subscription'

    def get_queryset(self):
        return super().get_queryset().select_related('service__category', 'payment_method')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        subscription = self.object
        payments = subscription.payments.select_related('payment_method')
        context.update(
            tags=subscription.tags.all(),
            payments=payments,
            total_paid=payments.aggregate(total=Sum('amount'))['total'] or 0,
            payment_form=PaymentForm(
                user=self.request.user,
                initial={
                    'amount': subscription.price,
                    'paid_at': timezone.localdate(),
                    'payment_method': subscription.payment_method_id,
                },
            ),
        )
        return context


class SubscriptionUpdateView(OwnedQuerysetMixin, OwnerFormMixin, SuccessMessageMixin, UpdateView):
    model = Subscription
    form_class = SubscriptionForm
    template_name = 'subscriptions/subscription_form.html'
    success_message = 'Изменения сохранены'

    def get_success_url(self):
        return reverse('subscriptions:detail', args=[self.object.pk])


class SubscriptionDeleteView(OwnedQuerysetMixin, SuccessMessageMixin, DeleteView):
    model = Subscription
    template_name = 'partials/confirm_delete.html'
    success_url = reverse_lazy('subscriptions:list')
    success_message = 'Подписка удалена'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        payments_count = self.object.payments.count()
        warning = 'Вместе с подпиской будет удалена история её платежей'
        if payments_count:
            warning += f" ({payments_count} {plural_ru(payments_count, 'платёж', 'платежа', 'платежей')})"
        context.update(
            cancel_url=reverse('subscriptions:detail', args=[self.object.pk]),
            delete_title='Удалить подписку?',
            delete_warning=warning + '.',
        )
        return context


class MarkPaidView(OwnedQuerysetMixin, SingleObjectMixin, View):
    """Отметка «оплачено»: создаёт Payment. Только POST — GET вернёт 405."""

    model = Subscription
    http_method_names = ['post']

    def post(self, request, *args, **kwargs):
        # get_object() идёт через OwnedQuerysetMixin: чужая подписка — 404.
        subscription = self.get_object()
        form = PaymentForm(request.POST, user=request.user)
        if form.is_valid():
            payment = form.save(commit=False)
            payment.subscription = subscription
            payment.save()
            messages.success(request, f'Платёж на {rub(payment.amount)} записан')
        else:
            problems = ' '.join(
                f"{form.fields[name].label if name in form.fields else 'Форма'}: {' '.join(errors)}"
                for name, errors in form.errors.items()
            )
            messages.error(request, f'Платёж не записан. {problems}')
        return redirect('subscriptions:detail', pk=subscription.pk)


class PaymentDeleteView(OwnedQuerysetMixin, DeleteView):
    """Удаление платежа. Владелец определяется через подписку."""

    model = Payment
    owner_field = 'subscription__user'
    http_method_names = ['post']

    def get_success_url(self):
        return reverse('subscriptions:detail', args=[self.object.subscription_id])

    def form_valid(self, form):
        response = super().form_valid(form)
        messages.success(self.request, f'Платёж на {rub(self.object.amount)} удалён')
        return response
