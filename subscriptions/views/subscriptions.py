# Временная заглушка: реализуется в этапе 2.
from django.views import View

SubscriptionListView = SubscriptionCreateView = SubscriptionDetailView = View
SubscriptionUpdateView = SubscriptionDeleteView = MarkPaidView = PaymentDeleteView = View
