from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.db.models import ProtectedError
from django.test import TestCase

from subscriptions.models import (
    BillingPeriod,
    BillingType,
    Category,
    NotificationLog,
    Payment,
    PaymentMethod,
    Service,
    Subscription,
    SubscriptionTag,
    Tag,
)

User = get_user_model()


class ModelTestBase(TestCase):
    """Общие данные. Категории и сервисы создаются свои (префикс test-),
    чтобы тесты не зависели от data-миграции с каталогом."""

    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user('user_a', email='a@example.com', password='pass12345')
        cls.other = User.objects.create_user('user_b', email='b@example.com', password='pass12345')
        cls.category = Category.objects.create(
            name='test-Категория', slug='test-category', color='#4F46E5'
        )
        cls.catalog_service = Service.objects.create(name='test-Каталожный', category=cls.category)

    def make_subscription(self, **kwargs):
        data = {
            'user': self.user,
            'service': self.catalog_service,
            'price': Decimal('299.00'),
            'billing_type': BillingType.MONTHLY,
            'start_date': date(2026, 1, 1),
        }
        data.update(kwargs)
        return Subscription.objects.create(**data)


class ServiceUniquenessTests(ModelTestBase):
    def test_catalog_service_name_unique(self):
        """Два каталожных сервиса (owner = NULL) с одним названием запрещены."""
        with transaction.atomic(), self.assertRaises(IntegrityError):
            Service.objects.create(name='test-Каталожный', category=self.category)

    def test_different_users_can_have_same_custom_name(self):
        """Разные пользователи могут завести свои сервисы с одинаковым названием."""
        Service.objects.create(name='test-Свой', category=self.category, owner=self.user)
        Service.objects.create(name='test-Свой', category=self.category, owner=self.other)
        self.assertEqual(Service.objects.filter(name='test-Свой').count(), 2)

    def test_custom_name_may_match_catalog_name(self):
        """Свой сервис может называться так же, как каталожный."""
        service = Service.objects.create(name='test-Каталожный', category=self.category, owner=self.user)
        self.assertTrue(service.is_custom)
        self.assertFalse(self.catalog_service.is_custom)

    def test_same_owner_same_name_forbidden(self):
        """Один владелец не может завести два сервиса с одинаковым названием."""
        Service.objects.create(name='test-Свой', category=self.category, owner=self.user)
        with transaction.atomic(), self.assertRaises(IntegrityError):
            Service.objects.create(name='test-Свой', category=self.category, owner=self.user)


class SubscriptionConstraintTests(ModelTestBase):
    def test_negative_price_forbidden(self):
        """CheckConstraint: цена не может быть отрицательной."""
        with transaction.atomic(), self.assertRaises(IntegrityError):
            self.make_subscription(price=Decimal('-1.00'))

    def test_trial_requires_end_date(self):
        """CheckConstraint: у пробного периода обязательна дата окончания."""
        with transaction.atomic(), self.assertRaises(IntegrityError):
            self.make_subscription(
                billing_type=BillingType.TRIAL,
                billing_period_after_trial=BillingPeriod.MONTHLY,
            )

    def test_trial_requires_period_after_trial(self):
        """CheckConstraint: у пробного периода обязательна периодичность после него."""
        with transaction.atomic(), self.assertRaises(IntegrityError):
            self.make_subscription(
                billing_type=BillingType.TRIAL,
                trial_end_date=date(2026, 1, 15),
            )

    def test_valid_trial_saves(self):
        """Корректный пробный период сохраняется."""
        sub = self.make_subscription(
            billing_type=BillingType.TRIAL,
            trial_end_date=date(2026, 1, 15),
            billing_period_after_trial=BillingPeriod.YEARLY,
        )
        sub.full_clean()
        self.assertIsNotNone(sub.pk)


class SubscriptionCleanTests(ModelTestBase):
    def build(self, **kwargs):
        data = {
            'user': self.user,
            'service': self.catalog_service,
            'price': Decimal('100.00'),
            'billing_type': BillingType.MONTHLY,
            'start_date': date(2026, 3, 1),
        }
        data.update(kwargs)
        return Subscription(**data)

    def test_trial_end_before_start(self):
        """Конец пробного периода раньше даты начала - ошибка валидации."""
        sub = self.build(
            billing_type=BillingType.TRIAL,
            trial_end_date=date(2026, 2, 1),
            billing_period_after_trial=BillingPeriod.MONTHLY,
        )
        with self.assertRaises(ValidationError) as ctx:
            sub.clean()
        self.assertIn('trial_end_date', ctx.exception.message_dict)

    def test_trial_without_fields_in_clean(self):
        """clean() сообщает о незаполненных полях пробного периода."""
        sub = self.build(billing_type=BillingType.TRIAL)
        with self.assertRaises(ValidationError) as ctx:
            sub.clean()
        self.assertIn('trial_end_date', ctx.exception.message_dict)
        self.assertIn('billing_period_after_trial', ctx.exception.message_dict)

    def test_foreign_payment_method(self):
        """Способ оплаты другого пользователя - ошибка валидации."""
        pm = PaymentMethod.objects.create(user=self.other, name='Чужая карта')
        sub = self.build(payment_method=pm)
        with self.assertRaises(ValidationError) as ctx:
            sub.clean()
        self.assertIn('payment_method', ctx.exception.message_dict)

    def test_own_payment_method_ok(self):
        """Свой способ оплаты проходит валидацию."""
        pm = PaymentMethod.objects.create(user=self.user, name='Своя карта')
        self.build(payment_method=pm).clean()

    def test_foreign_custom_service(self):
        """Свой сервис другого пользователя - ошибка валидации."""
        foreign = Service.objects.create(name='test-Чужой', category=self.category, owner=self.other)
        sub = self.build(service=foreign)
        with self.assertRaises(ValidationError) as ctx:
            sub.clean()
        self.assertIn('service', ctx.exception.message_dict)

    def test_own_custom_service_ok(self):
        """Собственный пользовательский сервис проходит валидацию."""
        own = Service.objects.create(name='test-Мой', category=self.category, owner=self.user)
        self.build(service=own).clean()

    def test_catalog_service_ok(self):
        """Сервис из каталога доступен любому пользователю."""
        self.build().clean()
        self.build(user=self.other).clean()


class SubscriptionPropertiesTests(ModelTestBase):
    def test_display_name_without_title(self):
        """Без названия тарифа отображается название сервиса."""
        sub = self.make_subscription()
        self.assertEqual(sub.display_name, 'test-Каталожный')
        self.assertEqual(str(sub), 'test-Каталожный')

    def test_display_name_with_title(self):
        """С названием тарифа - «Сервис - Тариф»."""
        sub = self.make_subscription(title='Семейный')
        self.assertEqual(sub.display_name, 'test-Каталожный (Семейный)')

    def test_category_goes_through_service(self):
        """Категория подписки берётся из сервиса."""
        sub = self.make_subscription()
        self.assertEqual(sub.category, self.category)


class SubscriptionTagTests(ModelTestBase):
    def test_tags_via_through_model(self):
        """M:N подписка ↔ тег работает через SubscriptionTag."""
        sub = self.make_subscription()
        family = Tag.objects.create(user=self.user, name='семья')
        work = Tag.objects.create(user=self.user, name='работа')
        SubscriptionTag.objects.create(subscription=sub, tag=family)
        sub.tags.add(work)
        self.assertEqual(set(sub.tags.all()), {family, work})
        self.assertEqual(list(family.subscriptions.all()), [sub])
        self.assertEqual(SubscriptionTag.objects.filter(subscription=sub).count(), 2)

    def test_duplicate_subscription_tag_forbidden(self):
        """Один и тот же тег нельзя повесить на подписку дважды."""
        sub = self.make_subscription()
        tag = Tag.objects.create(user=self.user, name='семья')
        SubscriptionTag.objects.create(subscription=sub, tag=tag)
        with transaction.atomic(), self.assertRaises(IntegrityError):
            SubscriptionTag.objects.create(subscription=sub, tag=tag)

    def test_duplicate_tag_name_per_user_forbidden(self):
        """У одного пользователя не может быть двух тегов с одним названием."""
        Tag.objects.create(user=self.user, name='семья')
        Tag.objects.create(user=self.other, name='семья')
        with transaction.atomic(), self.assertRaises(IntegrityError):
            Tag.objects.create(user=self.user, name='семья')

    def test_clean_rejects_foreign_tag(self):
        """SubscriptionTag.clean() не пропускает тег другого пользователя."""
        sub = self.make_subscription()
        foreign_tag = Tag.objects.create(user=self.other, name='чужой')
        with self.assertRaises(ValidationError):
            SubscriptionTag(subscription=sub, tag=foreign_tag).clean()

    def test_clean_accepts_own_tag(self):
        """Тег того же пользователя проходит валидацию."""
        sub = self.make_subscription()
        tag = Tag.objects.create(user=self.user, name='свой')
        SubscriptionTag(subscription=sub, tag=tag).clean()


class PaymentAndDeletionTests(ModelTestBase):
    def test_negative_amount_forbidden(self):
        """CheckConstraint: сумма платежа не может быть отрицательной."""
        sub = self.make_subscription()
        with transaction.atomic(), self.assertRaises(IntegrityError):
            Payment.objects.create(subscription=sub, amount=Decimal('-10.00'), paid_at=date(2026, 2, 1))

    def test_delete_payment_method_sets_null(self):
        """Удаление способа оплаты не удаляет платежи и подписки (SET_NULL)."""
        pm = PaymentMethod.objects.create(user=self.user, name='Карта', last4='1234')
        sub = self.make_subscription(payment_method=pm)
        payment = Payment.objects.create(
            subscription=sub, payment_method=pm, amount=Decimal('299.00'), paid_at=date(2026, 2, 1)
        )
        pm.delete()
        sub.refresh_from_db()
        payment.refresh_from_db()
        self.assertIsNone(sub.payment_method)
        self.assertIsNone(payment.payment_method)
        self.assertEqual(payment.amount, Decimal('299.00'))

    def test_delete_used_service_protected(self):
        """Сервис, на который есть подписка, удалить нельзя (PROTECT)."""
        service = Service.objects.create(name='test-Используемый', category=self.category)
        self.make_subscription(service=service)
        with self.assertRaises(ProtectedError):
            service.delete()

    def test_delete_used_category_protected(self):
        """Категорию, к которой привязан сервис, удалить нельзя (PROTECT)."""
        category = Category.objects.create(name='test-Другая', slug='test-other', color='#000000')
        Service.objects.create(name='test-В другой категории', category=category)
        with self.assertRaises(ProtectedError):
            category.delete()

    def test_delete_subscription_cascades_payments(self):
        """Удаление подписки удаляет её платежи (CASCADE)."""
        sub = self.make_subscription()
        Payment.objects.create(subscription=sub, amount=Decimal('1.00'), paid_at=date(2026, 2, 1))
        sub.delete()
        self.assertFalse(Payment.objects.exists())


class NotificationLogTests(ModelTestBase):
    def test_duplicate_notification_forbidden(self):
        """Одно и то же уведомление по одному событию нельзя записать дважды."""
        sub = self.make_subscription()
        data = {
            'subscription': sub,
            'kind': NotificationLog.Kind.TRIAL_ENDING,
            'channel': NotificationLog.Channel.EMAIL,
            'event_date': date(2026, 2, 1),
        }
        NotificationLog.objects.create(**data)
        with transaction.atomic(), self.assertRaises(IntegrityError):
            NotificationLog.objects.create(**data)

    def test_different_event_date_allowed(self):
        """То же уведомление с другой датой события - допустимо."""
        sub = self.make_subscription()
        data = {
            'subscription': sub,
            'kind': NotificationLog.Kind.TRIAL_ENDING,
            'channel': NotificationLog.Channel.EMAIL,
        }
        NotificationLog.objects.create(event_date=date(2026, 2, 1), **data)
        NotificationLog.objects.create(event_date=date(2026, 3, 1), **data)
        self.assertEqual(NotificationLog.objects.filter(subscription=sub).count(), 2)
