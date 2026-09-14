from django.apps import AppConfig


class CoreConfig(AppConfig):
    """Общие для всего проекта части: базовый шаблон, миксины форм, шаблонные фильтры."""

    default_auto_field = 'django.db.models.BigAutoField'
    name = 'core'
    verbose_name = 'Общее'
