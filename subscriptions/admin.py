from django.contrib import admin

from .models import (
    Category,
    NotificationLog,
    Payment,
    PaymentMethod,
    Service,
    Subscription,
    SubscriptionTag,
    Tag,
)

admin.site.site_header = 'Subscription Tracker: администрирование'
admin.site.site_title = 'Subscription Tracker: администрирование'


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ['name', 'slug', 'color', 'sort_order']
    list_editable = ['sort_order']
    prepopulated_fields = {'slug': ['name']}


class ServiceOriginFilter(admin.SimpleListFilter):
    """Каталог (owner = NULL) или пользовательский сервис."""

    title = 'происхождение'
    parameter_name = 'origin'

    def lookups(self, request, model_admin):
        return [('catalog', 'Каталог'), ('custom', 'Пользовательский')]

    def queryset(self, request, queryset):
        if self.value() == 'catalog':
            return queryset.filter(owner__isnull=True)
        if self.value() == 'custom':
            return queryset.filter(owner__isnull=False)
        return queryset


@admin.register(Service)
class ServiceAdmin(admin.ModelAdmin):
    list_display = ['name', 'category', 'owner', 'website']
    list_filter = ['category', ServiceOriginFilter]
    search_fields = ['name']
    list_select_related = ['category', 'owner']


@admin.register(PaymentMethod)
class PaymentMethodAdmin(admin.ModelAdmin):
    list_display = ['name', 'kind', 'last4', 'user']
    list_filter = ['user', 'kind']
    search_fields = ['name', 'last4', 'user__username']
    list_select_related = ['user']


@admin.register(Tag)
class TagAdmin(admin.ModelAdmin):
    list_display = ['name', 'user']
    list_filter = ['user']
    search_fields = ['name', 'user__username']
    list_select_related = ['user']


class SubscriptionTagInline(admin.TabularInline):
    model = SubscriptionTag
    extra = 1
    autocomplete_fields = ['tag']


class PaymentInline(admin.TabularInline):
    model = Payment
    extra = 0
    fields = ['amount', 'paid_at', 'payment_method']


@admin.register(Subscription)
class SubscriptionAdmin(admin.ModelAdmin):
    list_display = [
        'display_name',
        'user',
        'category',
        'price',
        'billing_type',
        'start_date',
        'trial_end_date',
        'is_active',
    ]
    list_filter = ['billing_type', 'is_active', 'service__category']
    search_fields = ['service__name', 'title', 'user__username']
    list_select_related = ['user', 'service__category']
    autocomplete_fields = ['service', 'payment_method']
    inlines = [SubscriptionTagInline, PaymentInline]
    fieldsets = [
        ('Основное', {'fields': ['user', 'service', 'title', 'payment_method']}),
        ('Оплата', {'fields': ['price', 'billing_type', 'start_date', 'is_active']}),
        ('Пробный период', {'fields': ['trial_end_date', 'billing_period_after_trial']}),
        ('Заметки', {'fields': ['notes']}),
    ]

    @admin.display(description='подписка', ordering='service__name')
    def display_name(self, obj):
        return obj.display_name

    @admin.display(description='категория', ordering='service__category__sort_order')
    def category(self, obj):
        return obj.service.category


@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    list_display = ['subscription', 'amount', 'paid_at', 'payment_method']
    list_filter = ['paid_at']
    date_hierarchy = 'paid_at'
    list_select_related = ['subscription__service', 'payment_method']
    autocomplete_fields = ['subscription', 'payment_method']


@admin.register(NotificationLog)
class NotificationLogAdmin(admin.ModelAdmin):
    """Журнал пишется только командами рассылки, вручную его не правим."""

    list_display = ['subscription', 'kind', 'channel', 'event_date', 'sent_at']
    list_filter = ['kind', 'channel']
    list_select_related = ['subscription__service']
    readonly_fields = ['subscription', 'kind', 'channel', 'event_date', 'sent_at']

    def has_add_permission(self, request):
        return False
