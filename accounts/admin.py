from django.contrib import admin
from django.contrib.auth import get_user_model
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin

from .models import UserProfile

User = get_user_model()


class UserProfileInline(admin.StackedInline):
    model = UserProfile
    can_delete = False  # профиль живёт и удаляется вместе с пользователем
    verbose_name_plural = 'профиль'


# Перерегистрируем встроенную админку User, чтобы профиль редактировался на той же странице.
admin.site.unregister(User)


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    inlines = [UserProfileInline]


@admin.register(UserProfile)
class UserProfileAdmin(admin.ModelAdmin):
    list_display = ['user', 'notification_email', 'notify_days_before', 'monthly_budget']
    search_fields = ['user__username', 'user__email', 'notification_email']
    list_select_related = ['user']
