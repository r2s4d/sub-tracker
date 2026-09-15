from django.contrib.auth.views import LogoutView
from django.urls import path

from . import views

# Имена login/logout без namespace - их ожидают настройки LOGIN_URL и шаблоны Django.
urlpatterns = [
    path('login/', views.SignInView.as_view(), name='login'),
    path('logout/', LogoutView.as_view(), name='logout'),
    path('signup/', views.SignUpView.as_view(), name='signup'),
    path('profile/', views.ProfileView.as_view(), name='profile'),
]
