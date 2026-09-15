"""Справочники владельца: способы оплаты, теги и свои сервисы."""

from datetime import date
from decimal import Decimal

from django.test import TestCase
from django.urls import reverse

from .utils import (
    Payment,
    PaymentMethod,
    Service,
    Tag,
    make_category,
    make_subscription,
    make_user,
)


class ReferenceViewTestBase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = make_user('owner_a')
        cls.other = make_user('other_b')
        cls.category = make_category('refs')
        cls.catalog_service = Service.objects.create(name='test-Каталожный', category=cls.category)

    def setUp(self):
        self.client.force_login(self.user)


class PaymentMethodViewTests(ReferenceViewTestBase):
    list_url = reverse('subscriptions:paymentmethod-list')
    create_url = reverse('subscriptions:paymentmethod-create')

    def test_list_shows_own_methods_with_usage(self):
        """Список способов оплаты показывает карту и число подписок на ней."""
        card = PaymentMethod.objects.create(user=self.user, name='test-Т-Банк', last4='1234')
        make_subscription(self.user, self.catalog_service, payment_method=card)
        response = self.client.get(self.list_url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'test-Т-Банк')
        self.assertContains(response, '1 подписка')

    def test_create(self):
        """Создание способа оплаты - владелец текущий пользователь, редирект на список."""
        response = self.client.post(self.create_url, {'name': 'test-Сбер', 'kind': 'card', 'last4': '5678'})
        self.assertRedirects(response, self.list_url)
        card = PaymentMethod.objects.get(name='test-Сбер')
        self.assertEqual(card.user, self.user)
        self.assertEqual(card.last4, '5678')

    def test_create_rejects_bad_last4(self):
        """last4 не из четырёх цифр - ошибка формы."""
        response = self.client.post(self.create_url, {'name': 'test-Сбер', 'kind': 'card', 'last4': '12a4'})
        self.assertEqual(response.status_code, 200)
        self.assertIn('last4', response.context['form'].errors)
        self.assertFalse(PaymentMethod.objects.exists())

    def test_update(self):
        """Изменение способа оплаты сохраняется."""
        card = PaymentMethod.objects.create(user=self.user, name='test-Старая', last4='1111')
        response = self.client.post(
            reverse('subscriptions:paymentmethod-update', args=[card.pk]),
            {'name': 'test-Новая', 'kind': 'account', 'last4': ''},
        )
        self.assertRedirects(response, self.list_url)
        card.refresh_from_db()
        self.assertEqual((card.name, card.kind, card.last4), ('test-Новая', 'account', ''))

    def test_delete_sets_null_on_subscriptions_and_payments(self):
        """Удаление карты: подписки и платежи остаются, у них просто пропадает способ оплаты."""
        card = PaymentMethod.objects.create(user=self.user, name='test-Удаляемая')
        subscription = make_subscription(self.user, self.catalog_service, payment_method=card)
        payment = Payment.objects.create(
            subscription=subscription, payment_method=card, amount=Decimal('299.00'), paid_at=date(2026, 2, 1),
        )
        url = reverse('subscriptions:paymentmethod-delete', args=[card.pk])
        self.assertEqual(self.client.get(url).status_code, 200)
        response = self.client.post(url)
        self.assertRedirects(response, self.list_url)
        self.assertFalse(PaymentMethod.objects.filter(pk=card.pk).exists())
        subscription.refresh_from_db()
        payment.refresh_from_db()
        self.assertIsNone(subscription.payment_method)
        self.assertIsNone(payment.payment_method)
        self.assertEqual(payment.amount, Decimal('299.00'))


class TagViewTests(ReferenceViewTestBase):
    list_url = reverse('subscriptions:tag-list')
    create_url = reverse('subscriptions:tag-create')

    def test_create(self):
        """Создание тега - владелец текущий пользователь, пробелы по краям обрезаются."""
        response = self.client.post(self.create_url, {'name': '  test-семья  '})
        self.assertRedirects(response, self.list_url)
        tag = Tag.objects.get(name='test-семья')
        self.assertEqual(tag.user, self.user)

    def test_list_shows_tags(self):
        """Список тегов показывает свои теги."""
        Tag.objects.create(user=self.user, name='test-работа')
        response = self.client.get(self.list_url)
        self.assertContains(response, 'test-работа')

    def test_duplicate_name_case_insensitive_is_form_error(self):
        """Тег с таким же названием в другом регистре - ошибка формы, а не 500."""
        Tag.objects.create(user=self.user, name='test-Семья')
        response = self.client.post(self.create_url, {'name': 'TEST-СЕМЬЯ'})
        self.assertEqual(response.status_code, 200)
        self.assertFormError(response.context['form'], 'name', 'У вас уже есть тег с таким названием.')
        self.assertEqual(Tag.objects.filter(user=self.user).count(), 1)

    def test_duplicate_exact_name_is_form_error(self):
        """Точный дубль названия - тоже ошибка формы (без IntegrityError)."""
        Tag.objects.create(user=self.user, name='test-семья')
        response = self.client.post(self.create_url, {'name': 'test-семья'})
        self.assertEqual(response.status_code, 200)
        self.assertIn('name', response.context['form'].errors)

    def test_rename_to_existing_name_is_form_error(self):
        """Переименование тега в название другого своего тега - ошибка формы."""
        Tag.objects.create(user=self.user, name='test-семья')
        work = Tag.objects.create(user=self.user, name='test-работа')
        response = self.client.post(reverse('subscriptions:tag-update', args=[work.pk]), {'name': 'Test-Семья'})
        self.assertEqual(response.status_code, 200)
        self.assertIn('name', response.context['form'].errors)
        work.refresh_from_db()
        self.assertEqual(work.name, 'test-работа')

    def test_same_name_as_other_users_tag_is_allowed(self):
        """Название, совпадающее с тегом другого пользователя, допустимо."""
        Tag.objects.create(user=self.other, name='test-семья')
        response = self.client.post(self.create_url, {'name': 'test-семья'})
        self.assertRedirects(response, self.list_url)
        self.assertTrue(Tag.objects.filter(user=self.user, name='test-семья').exists())

    def test_update_changes_case_of_own_name(self):
        """Смена регистра в названии своего тега не считается дублем."""
        tag = Tag.objects.create(user=self.user, name='test-семья')
        response = self.client.post(reverse('subscriptions:tag-update', args=[tag.pk]), {'name': 'test-Семья'})
        self.assertRedirects(response, self.list_url)
        tag.refresh_from_db()
        self.assertEqual(tag.name, 'test-Семья')

    def test_delete_unlinks_from_subscriptions(self):
        """Удаление тега снимает его с подписок, сами подписки остаются."""
        tag = Tag.objects.create(user=self.user, name='test-временный')
        subscription = make_subscription(self.user, self.catalog_service)
        subscription.tags.add(tag)
        url = reverse('subscriptions:tag-delete', args=[tag.pk])
        self.assertContains(self.client.get(url), 'в 1 подписке')
        response = self.client.post(url)
        self.assertRedirects(response, self.list_url)
        self.assertFalse(Tag.objects.filter(pk=tag.pk).exists())
        self.assertEqual(list(subscription.tags.all()), [])


class ServiceViewTests(ReferenceViewTestBase):
    list_url = reverse('subscriptions:service-list')
    create_url = reverse('subscriptions:service-create')

    def service_data(self, name, **extra):
        return {'name': name, 'category': self.category.pk, 'website': '', **extra}

    def test_list_shows_own_and_catalog(self):
        """Список сервисов показывает свои сервисы и общий каталог отдельно."""
        own = Service.objects.create(name='test-Мой-VPS', category=self.category, owner=self.user)
        response = self.client.get(self.list_url)
        self.assertEqual(list(response.context['own_services']), [own])
        self.assertIn(self.catalog_service, response.context['catalog'])

    def test_create(self):
        """Создание своего сервиса - владелец текущий пользователь."""
        response = self.client.post(self.create_url, self.service_data('test-Хостинг', website='https://host.example'))
        self.assertRedirects(response, self.list_url)
        service = Service.objects.get(name='test-Хостинг')
        self.assertEqual(service.owner, self.user)
        self.assertEqual(service.website, 'https://host.example')

    def test_update(self):
        """Изменение своего сервиса сохраняется."""
        service = Service.objects.create(name='test-Старый', category=self.category, owner=self.user)
        response = self.client.post(
            reverse('subscriptions:service-update', args=[service.pk]), self.service_data('test-Новый'),
        )
        self.assertRedirects(response, self.list_url)
        service.refresh_from_db()
        self.assertEqual(service.name, 'test-Новый')
        self.assertEqual(service.owner, self.user)

    def test_name_duplicating_catalog_is_form_error(self):
        """Название, которое уже есть в каталоге (в любом регистре), - ошибка формы."""
        response = self.client.post(self.create_url, self.service_data('TEST-каталожный'))
        self.assertEqual(response.status_code, 200)
        self.assertIn('name', response.context['form'].errors)
        self.assertFalse(Service.objects.filter(owner=self.user).exists())

    def test_name_duplicating_own_service_is_form_error(self):
        """Название своего же сервиса (в другом регистре) - ошибка формы, а не IntegrityError."""
        Service.objects.create(name='test-Мой', category=self.category, owner=self.user)
        response = self.client.post(self.create_url, self.service_data('TEST-МОЙ'))
        self.assertEqual(response.status_code, 200)
        self.assertFormError(response.context['form'], 'name', 'У вас уже есть сервис с таким названием.')
        self.assertEqual(Service.objects.filter(owner=self.user).count(), 1)

    def test_rename_to_own_existing_name_is_form_error(self):
        """Переименование в название другого своего сервиса - ошибка формы."""
        Service.objects.create(name='test-Первый', category=self.category, owner=self.user)
        second = Service.objects.create(name='test-Второй', category=self.category, owner=self.user)
        response = self.client.post(
            reverse('subscriptions:service-update', args=[second.pk]), self.service_data('test-Первый'),
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn('name', response.context['form'].errors)

    def test_same_name_as_other_users_service_is_allowed(self):
        """Название, совпадающее со своим сервисом другого пользователя, допустимо."""
        Service.objects.create(name='test-Общее-имя', category=self.category, owner=self.other)
        response = self.client.post(self.create_url, self.service_data('test-Общее-имя'))
        self.assertRedirects(response, self.list_url)
        self.assertTrue(Service.objects.filter(owner=self.user, name='test-Общее-имя').exists())

    def test_delete_unused_service(self):
        """Неиспользуемый свой сервис удаляется."""
        service = Service.objects.create(name='test-Ненужный', category=self.category, owner=self.user)
        url = reverse('subscriptions:service-delete', args=[service.pk])
        self.assertContains(self.client.get(url), 'Удалить сервис?')
        response = self.client.post(url)
        self.assertRedirects(response, self.list_url)
        self.assertFalse(Service.objects.filter(pk=service.pk).exists())

    def test_delete_page_for_used_service_explains_why_not(self):
        """Страница удаления используемого сервиса объясняет, что удалить нельзя."""
        service = Service.objects.create(name='test-Нужный', category=self.category, owner=self.user)
        make_subscription(self.user, service)
        response = self.client.get(reverse('subscriptions:service-delete', args=[service.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Сервис нельзя удалить')

    def test_delete_used_service_shows_message_and_keeps_service(self):
        """POST на удаление используемого сервиса - понятное сообщение, сервис на месте (не 500)."""
        service = Service.objects.create(name='test-Нужный', category=self.category, owner=self.user)
        make_subscription(self.user, service)
        response = self.client.post(reverse('subscriptions:service-delete', args=[service.pk]), follow=True)
        self.assertRedirects(response, self.list_url)
        self.assertContains(response, 'Нельзя удалить: сервис используется в 1 подписке.')
        self.assertTrue(Service.objects.filter(pk=service.pk).exists())


class SafeNextRedirectTests(ReferenceViewTestBase):
    """?next= после создания карты/сервиса: свой адрес - возврат туда, чужой - игнор."""

    local_next = reverse('subscriptions:create')
    evil_urls = ['https://evil.example/', '//evil.example/', 'http://evil.example/steal']

    def creation_cases(self):
        return [
            ('способ оплаты', reverse('subscriptions:paymentmethod-create'),
             lambda n: {'name': f'test-Карта-{n}', 'kind': 'card', 'last4': ''},
             reverse('subscriptions:paymentmethod-list')),
            ('сервис', reverse('subscriptions:service-create'),
             lambda n: {'name': f'test-Сервис-{n}', 'category': self.category.pk, 'website': ''},
             reverse('subscriptions:service-list')),
        ]

    def test_local_next_in_query_string_is_followed(self):
        """?next=/subscriptions/new/ в URL - после создания возврат на форму подписки."""
        for label, url, data, _ in self.creation_cases():
            with self.subTest(label):
                response = self.client.post(f'{url}?next={self.local_next}', data('query'))
                self.assertRedirects(response, self.local_next)

    def test_local_next_in_post_body_is_followed(self):
        """next в теле POST (скрытое поле формы) тоже работает."""
        for label, url, data, _ in self.creation_cases():
            with self.subTest(label):
                response = self.client.post(url, {**data('body'), 'next': self.local_next})
                self.assertRedirects(response, self.local_next)

    def test_external_next_is_ignored(self):
        """Внешний next (https://evil.example и т.п.) игнорируется - редирект на список."""
        for label, url, data, list_url in self.creation_cases():
            for i, evil in enumerate(self.evil_urls):
                with self.subTest(label, next=evil):
                    response = self.client.post(url, {**data(f'evil{i}'), 'next': evil})
                    self.assertRedirects(response, list_url)

    def test_external_next_not_rendered_as_cancel_link(self):
        """Внешний next не попадает в ссылку «Отмена» на форме."""
        for label, url, _, list_url in self.creation_cases():
            with self.subTest(label):
                response = self.client.get(url, {'next': 'https://evil.example/'})
                self.assertIsNone(response.context['next_url'])
                self.assertEqual(str(response.context['cancel_url']), list_url)
                self.assertNotContains(response, 'evil.example')
