from django.urls import path

from .views import dashboard, references, subscriptions

app_name = 'subscriptions'

urlpatterns = [
    path('dashboard/', dashboard.DashboardView.as_view(), name='dashboard'),

    # Подписки
    path('', subscriptions.SubscriptionListView.as_view(), name='list'),
    path('new/', subscriptions.SubscriptionCreateView.as_view(), name='create'),
    path('<int:pk>/', subscriptions.SubscriptionDetailView.as_view(), name='detail'),
    path('<int:pk>/edit/', subscriptions.SubscriptionUpdateView.as_view(), name='update'),
    path('<int:pk>/delete/', subscriptions.SubscriptionDeleteView.as_view(), name='delete'),
    path('<int:pk>/pay/', subscriptions.MarkPaidView.as_view(), name='mark-paid'),
    path('payments/<int:pk>/delete/', subscriptions.PaymentDeleteView.as_view(), name='payment-delete'),

    # Способы оплаты
    path('cards/', references.PaymentMethodListView.as_view(), name='paymentmethod-list'),
    path('cards/new/', references.PaymentMethodCreateView.as_view(), name='paymentmethod-create'),
    path('cards/<int:pk>/edit/', references.PaymentMethodUpdateView.as_view(), name='paymentmethod-update'),
    path('cards/<int:pk>/delete/', references.PaymentMethodDeleteView.as_view(), name='paymentmethod-delete'),

    # Теги
    path('tags/', references.TagListView.as_view(), name='tag-list'),
    path('tags/new/', references.TagCreateView.as_view(), name='tag-create'),
    path('tags/<int:pk>/edit/', references.TagUpdateView.as_view(), name='tag-update'),
    path('tags/<int:pk>/delete/', references.TagDeleteView.as_view(), name='tag-delete'),

    # Сервисы: каталог (только просмотр) + свои (полный CRUD)
    path('services/', references.ServiceListView.as_view(), name='service-list'),
    path('services/new/', references.ServiceCreateView.as_view(), name='service-create'),
    path('services/<int:pk>/edit/', references.ServiceUpdateView.as_view(), name='service-update'),
    path('services/<int:pk>/delete/', references.ServiceDeleteView.as_view(), name='service-delete'),
]
