from django.shortcuts import redirect


def home(request):
    """Корень сайта: гостя — на вход, пользователя — к списку подписок.

    На этапе 3 пользователь будет попадать на дашборд.
    """
    if request.user.is_authenticated:
        return redirect('subscriptions:list')
    return redirect('login')
