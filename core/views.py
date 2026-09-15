from django.shortcuts import redirect


def home(request):
    """Корень сайта: гостя - на вход, пользователя - на дашборд."""
    if request.user.is_authenticated:
        return redirect('subscriptions:dashboard')
    return redirect('login')
