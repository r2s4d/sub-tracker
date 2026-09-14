"""Миксины изоляции данных между пользователями.

Главное правило этапа 2: пользователь А не видит и не может изменить данные
пользователя Б. Оно реализовано в одном месте — через get_queryset(), —
а не проверкой «if obj.user != request.user» в каждом view.

Если объект чужой, он просто не попадает в queryset, и DetailView/UpdateView/
DeleteView отдают 404. Это лучше, чем 403: посторонний даже не узнаёт,
что запись с таким id существует.
"""

from django.contrib.auth.mixins import LoginRequiredMixin


class OwnedQuerysetMixin(LoginRequiredMixin):
    """Ограничивает queryset объектами текущего пользователя.

    owner_field — путь к полю пользователя, например 'user' или 'subscription__user'.
    """

    owner_field = 'user'

    def get_queryset(self):
        return super().get_queryset().filter(**{self.owner_field: self.request.user})


class OwnerFormMixin(LoginRequiredMixin):
    """Передаёт пользователя в форму и назначает его владельцем новой записи.

    Форма получает user, чтобы ограничить выпадающие списки (карты, теги,
    сервисы) только своими записями. Поле user в форме не показывается —
    подменить владельца через POST невозможно.
    """

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['user'] = self.request.user
        return kwargs

    def form_valid(self, form):
        form.instance.user = self.request.user
        return super().form_valid(form)
