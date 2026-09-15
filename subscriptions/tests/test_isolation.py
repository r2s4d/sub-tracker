"""Изоляция данных между пользователями - главный критерий готовности этапа 2.

DoD: «пользователь А не видит и не может отредактировать подписки пользователя Б».

Сценарий: у пользователей А и Б одинаковый набор данных - подписка на
сервис из каталога, пробная подписка на свой сервис, платёж, способ оплаты,
тег. Дальше Б пытается увидеть, открыть, изменить и удалить данные А всеми
доступными путями (списки, прямые URL, подмена id в формах, фильтры),
а тесты проверяют, что ничего из этого не работает и данные А в БД не меняются.
"""

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from types import SimpleNamespace

from django.test import TestCase
from django.urls import reverse

from subscriptions.models import SubscriptionTag

from .utils import (
    Payment,
    PaymentMethod,
    Service,
    Subscription,
    Tag,
    login_redirect_url,
    make_category,
    make_subscription,
    make_trial,
    make_user,
    subscription_post_data,
)


@dataclass
class Endpoint:
    """Одна строка чек-листа: что пытаемся открыть и с какими данными."""

    label: str
    url: str
    post_data: dict = field(default_factory=dict)
    allows_get: bool = True
    allows_post: bool = True

    @property
    def expected_post_status(self):
        # Карточка подписки принимает только GET: POST на неё - 405 (объект даже не ищется).
        return 404 if self.allows_post else 405


def build_user_world(user, label, catalog_service, category):
    """Полный набор данных одного пользователя. Все названия содержат метку (A/B)."""
    payment_method = PaymentMethod.objects.create(user=user, name=f'test-{label}-карта', last4='1111')
    tag = Tag.objects.create(user=user, name=f'test-{label}-тег')
    custom_service = Service.objects.create(
        name=f'test-{label}-свой-сервис', category=category, owner=user,
    )
    subscription = make_subscription(
        user, catalog_service, title=f'test-{label}-тариф', payment_method=payment_method,
    )
    subscription.tags.add(tag)
    trial = make_trial(user, custom_service, title=f'test-{label}-пробный')
    trial.tags.add(tag)
    payment = Payment.objects.create(
        subscription=subscription, payment_method=payment_method,
        amount=Decimal('299.00'), paid_at=date(2026, 2, 1),
    )
    return SimpleNamespace(
        user=user,
        payment_method=payment_method,
        tag=tag,
        custom_service=custom_service,
        subscription=subscription,
        trial=trial,
        payment=payment,
        secret_names=[
            payment_method.name, tag.name, custom_service.name, subscription.title, trial.title,
        ],
    )


def snapshot(user):
    """Состояние всех данных пользователя в БД - для сравнения «до» и «после»."""
    return {
        'subscriptions': list(Subscription.objects.filter(user=user).order_by('pk').values()),
        'payments': list(Payment.objects.filter(subscription__user=user).order_by('pk').values()),
        'payment_methods': list(PaymentMethod.objects.filter(user=user).order_by('pk').values()),
        'tags': list(Tag.objects.filter(user=user).order_by('pk').values()),
        'services': list(Service.objects.filter(owner=user).order_by('pk').values()),
        'subscription_tags': list(
            SubscriptionTag.objects.filter(subscription__user=user).order_by('pk').values()
        ),
    }


def object_endpoints(world, catalog_service, category):
    """Чек-лист URL, ведущих к конкретным объектам пользователя world.

    POST-данные валидные: если бы защита не сработала, изменение
    действительно сохранилось бы, и тест это заметил бы.
    """
    sub_pk = world.subscription.pk
    return [
        Endpoint('карточка подписки', reverse('subscriptions:detail', args=[sub_pk]), allows_post=False),
        Endpoint(
            'редактирование подписки', reverse('subscriptions:update', args=[sub_pk]),
            subscription_post_data(catalog_service, title='взломано', price='1.00'),
        ),
        Endpoint('удаление подписки', reverse('subscriptions:delete', args=[sub_pk])),
        Endpoint(
            'редактирование пробной подписки', reverse('subscriptions:update', args=[world.trial.pk]),
            subscription_post_data(catalog_service, title='взломано'),
        ),
        Endpoint('удаление пробной подписки', reverse('subscriptions:delete', args=[world.trial.pk])),
        Endpoint(
            'отметка оплаты', reverse('subscriptions:mark-paid', args=[sub_pk]),
            {'amount': '1.00', 'paid_at': '2026-03-01', 'payment_method': ''},
            allows_get=False,
        ),
        Endpoint(
            'удаление платежа', reverse('subscriptions:payment-delete', args=[world.payment.pk]),
            allows_get=False,
        ),
        Endpoint(
            'редактирование способа оплаты',
            reverse('subscriptions:paymentmethod-update', args=[world.payment_method.pk]),
            {'name': 'взломано', 'kind': 'card', 'last4': '9999'},
        ),
        Endpoint(
            'удаление способа оплаты',
            reverse('subscriptions:paymentmethod-delete', args=[world.payment_method.pk]),
        ),
        Endpoint(
            'редактирование тега', reverse('subscriptions:tag-update', args=[world.tag.pk]),
            {'name': 'взломано'},
        ),
        Endpoint('удаление тега', reverse('subscriptions:tag-delete', args=[world.tag.pk])),
        Endpoint(
            'редактирование своего сервиса',
            reverse('subscriptions:service-update', args=[world.custom_service.pk]),
            {'name': 'test-взломано', 'category': category.pk, 'website': ''},
        ),
        Endpoint(
            'удаление своего сервиса',
            reverse('subscriptions:service-delete', args=[world.custom_service.pk]),
        ),
    ]


def collection_endpoints(catalog_service, category):
    """Чек-лист URL без конкретного объекта: списки и формы создания."""
    return [
        Endpoint('список подписок', reverse('subscriptions:list')),
        Endpoint(
            'создание подписки', reverse('subscriptions:create'),
            subscription_post_data(catalog_service, title='test-аноним'),
        ),
        Endpoint('список способов оплаты', reverse('subscriptions:paymentmethod-list')),
        Endpoint(
            'создание способа оплаты', reverse('subscriptions:paymentmethod-create'),
            {'name': 'test-аноним', 'kind': 'card', 'last4': ''},
        ),
        Endpoint('список тегов', reverse('subscriptions:tag-list')),
        Endpoint('создание тега', reverse('subscriptions:tag-create'), {'name': 'test-аноним'}),
        Endpoint('список сервисов', reverse('subscriptions:service-list')),
        Endpoint(
            'создание сервиса', reverse('subscriptions:service-create'),
            {'name': 'test-аноним', 'category': category.pk, 'website': ''},
        ),
    ]


class IsolationTestBase(TestCase):
    """Два пользователя с одинаковым набором данных. Клиент по умолчанию - Б."""

    @classmethod
    def setUpTestData(cls):
        cls.category = make_category('isolation')
        cls.catalog_service = Service.objects.create(name='test-Каталог-общий', category=cls.category)
        cls.a = build_user_world(make_user('user_a'), 'A', cls.catalog_service, cls.category)
        cls.b = build_user_world(make_user('user_b'), 'B', cls.catalog_service, cls.category)

    def setUp(self):
        self.client.force_login(self.b.user)

    def assert_no_secrets_of_a(self, response):
        for name in self.a.secret_names:
            self.assertNotContains(response, name, msg_prefix=f'На странице видно «{name}» пользователя А')


class ForeignDataInListsTests(IsolationTestBase):
    """Списки Б содержат только его данные."""

    def test_subscription_list_shows_only_own_subscriptions(self):
        """В списке подписок Б (все статусы) - только его подписки, названий подписок А нет."""
        response = self.client.get(reverse('subscriptions:list'), {'status': 'all'})
        self.assertEqual(set(response.context['subscriptions']), {self.b.subscription, self.b.trial})
        self.assert_no_secrets_of_a(response)
        self.assertContains(response, self.b.subscription.title)  # страница не пустая - проверка не холостая

    def test_subscription_list_default_filter_shows_only_own(self):
        """Список подписок с фильтром по умолчанию тоже не содержит данных А."""
        response = self.client.get(reverse('subscriptions:list'))
        self.assertEqual(set(response.context['subscriptions']), {self.b.subscription, self.b.trial})
        self.assert_no_secrets_of_a(response)

    def test_tag_filter_dropdown_offers_only_own_tags(self):
        """В фильтре по тегам на странице подписок - только теги Б."""
        response = self.client.get(reverse('subscriptions:list'))
        self.assertEqual(list(response.context['tags']), [self.b.tag])

    def test_payment_method_list_shows_only_own(self):
        """В списке способов оплаты Б нет карт А."""
        response = self.client.get(reverse('subscriptions:paymentmethod-list'))
        self.assertEqual(list(response.context['payment_methods']), [self.b.payment_method])
        self.assert_no_secrets_of_a(response)
        self.assertContains(response, self.b.payment_method.name)

    def test_tag_list_shows_only_own(self):
        """В списке тегов Б нет тегов А."""
        response = self.client.get(reverse('subscriptions:tag-list'))
        self.assertEqual(list(response.context['tags']), [self.b.tag])
        self.assert_no_secrets_of_a(response)
        self.assertContains(response, self.b.tag.name)

    def test_service_list_shows_only_own_custom_services(self):
        """В списке сервисов Б: свои сервисы - только его, в каталоге - только общие."""
        response = self.client.get(reverse('subscriptions:service-list'))
        self.assertEqual(list(response.context['own_services']), [self.b.custom_service])
        self.assertNotIn(self.a.custom_service, list(response.context['catalog']))
        self.assertTrue(all(service.owner_id is None for service in response.context['catalog']))
        self.assert_no_secrets_of_a(response)
        self.assertContains(response, self.b.custom_service.name)

    def test_service_search_does_not_find_foreign_services(self):
        """Поиск по сервисам не находит свой сервис А даже по точному названию.

        Само название на странице есть - это эхо запроса Б («нет «…»»), поэтому
        проверяем результаты поиска и отсутствие ссылок на сервис А.
        """
        response = self.client.get(reverse('subscriptions:service-list'), {'q': self.a.custom_service.name})
        self.assertEqual(list(response.context['own_services']), [])
        self.assertEqual(list(response.context['catalog']), [])
        self.assertNotContains(response, reverse('subscriptions:service-update', args=[self.a.custom_service.pk]))
        self.assertNotContains(response, reverse('subscriptions:service-delete', args=[self.a.custom_service.pk]))

    def test_filter_by_foreign_tag_shows_nothing(self):
        """Фильтр ?tag=<id тега А> в списке Б не показывает подписки А."""
        response = self.client.get(reverse('subscriptions:list'), {'tag': self.a.tag.pk, 'status': 'all'})
        self.assertEqual(list(response.context['subscriptions']), [])
        self.assert_no_secrets_of_a(response)

    def test_subscription_form_offers_only_own_references(self):
        """Форма новой подписки Б не предлагает карты, теги и свои сервисы А."""
        response = self.client.get(reverse('subscriptions:create'))
        form = response.context['form']
        self.assertEqual(list(form.fields['payment_method'].queryset), [self.b.payment_method])
        self.assertEqual(list(form.fields['tags'].queryset), [self.b.tag])
        self.assertNotIn(self.a.custom_service, form.fields['service'].queryset)
        self.assertIn(self.b.custom_service, form.fields['service'].queryset)
        self.assert_no_secrets_of_a(response)

    def test_own_detail_page_offers_only_own_payment_methods(self):
        """В форме «оплачено» на карточке подписки Б нет карт А."""
        response = self.client.get(reverse('subscriptions:detail', args=[self.b.subscription.pk]))
        self.assertEqual(
            list(response.context['payment_form'].fields['payment_method'].queryset),
            [self.b.payment_method],
        )
        self.assert_no_secrets_of_a(response)


class ForeignObjectUrlTests(IsolationTestBase):
    """Прямые URL к объектам А открываются у Б как несуществующие (404)."""

    def endpoints(self):
        return object_endpoints(self.a, self.catalog_service, self.category)

    def test_get_foreign_objects_returns_404(self):
        """GET на карточку, редактирование и удаление любого объекта А - 404."""
        for endpoint in self.endpoints():
            if not endpoint.allows_get:
                continue
            with self.subTest(endpoint.label, url=endpoint.url):
                response = self.client.get(endpoint.url)
                self.assertEqual(response.status_code, 404)

    def test_post_to_foreign_objects_returns_404_and_changes_nothing(self):
        """POST на изменение/удаление любого объекта А - 404, данные А в БД не меняются."""
        for endpoint in self.endpoints():
            with self.subTest(endpoint.label, url=endpoint.url):
                before = snapshot(self.a.user)
                response = self.client.post(endpoint.url, endpoint.post_data)
                self.assertEqual(response.status_code, endpoint.expected_post_status)
                self.assertEqual(snapshot(self.a.user), before)

    def test_post_only_urls_reject_get_without_touching_object(self):
        """GET на «оплачено» и удаление платежа А - 405, как и для своих: объект не ищется."""
        for endpoint in self.endpoints():
            if endpoint.allows_get:
                continue
            with self.subTest(endpoint.label, url=endpoint.url):
                self.assertEqual(self.client.get(endpoint.url).status_code, 405)

    def test_foreign_data_of_b_is_also_protected_from_a(self):
        """Проверка симметрична: А тоже получает 404 на объекты Б."""
        self.client.force_login(self.a.user)
        before = snapshot(self.b.user)
        for endpoint in object_endpoints(self.b, self.catalog_service, self.category):
            with self.subTest(endpoint.label, url=endpoint.url):
                response = self.client.post(endpoint.url, endpoint.post_data)
                self.assertEqual(response.status_code, endpoint.expected_post_status)
        self.assertEqual(snapshot(self.b.user), before)

    def test_own_objects_are_reachable(self):
        """Контроль: те же URL для собственных объектов Б открываются (200), т.е. 404 выше - не случайность."""
        for endpoint in object_endpoints(self.b, self.catalog_service, self.category):
            if not endpoint.allows_get:
                continue
            with self.subTest(endpoint.label, url=endpoint.url):
                self.assertEqual(self.client.get(endpoint.url).status_code, 200)


class ForeignReferencesInFormsTests(IsolationTestBase):
    """Подмена id в POST: чужую карту, тег или сервис нельзя привязать к своей подписке."""

    def foreign_reference_cases(self):
        """(описание, поле формы с ошибкой, POST-данные с id объекта А)."""
        base = {'title': 'test-B-новая'}
        return [
            ('карта А', 'payment_method',
             subscription_post_data(self.catalog_service, payment_method=self.a.payment_method.pk, **base)),
            ('тег А', 'tags',
             subscription_post_data(self.catalog_service, tags=[self.a.tag.pk], **base)),
            ('свой сервис А', 'service',
             subscription_post_data(self.a.custom_service, **base)),
        ]

    def test_create_with_foreign_reference_is_rejected(self):
        """Создание подписки Б с id карты/тега/сервиса А - ошибка формы, ничего не сохранено."""
        for label, field_name, data in self.foreign_reference_cases():
            with self.subTest(label):
                subscriptions_before = Subscription.objects.count()
                links_before = SubscriptionTag.objects.count()
                response = self.client.post(reverse('subscriptions:create'), data)
                self.assertEqual(response.status_code, 200)
                self.assertIn(field_name, response.context['form'].errors)
                self.assertEqual(Subscription.objects.count(), subscriptions_before)
                self.assertEqual(SubscriptionTag.objects.count(), links_before)

    def test_update_with_foreign_reference_is_rejected(self):
        """Изменение подписки Б с id карты/тега/сервиса А - ошибка формы, подписка Б не изменилась."""
        url = reverse('subscriptions:update', args=[self.b.subscription.pk])
        for label, field_name, data in self.foreign_reference_cases():
            with self.subTest(label):
                before_b = snapshot(self.b.user)
                before_a = snapshot(self.a.user)
                response = self.client.post(url, data)
                self.assertEqual(response.status_code, 200)
                self.assertIn(field_name, response.context['form'].errors)
                self.assertEqual(snapshot(self.b.user), before_b)
                self.assertEqual(snapshot(self.a.user), before_a)

    def test_mark_paid_with_foreign_payment_method_is_rejected(self):
        """Отметка оплаты своей подписки картой А - платёж не создаётся."""
        payments_before = Payment.objects.count()
        response = self.client.post(
            reverse('subscriptions:mark-paid', args=[self.b.subscription.pk]),
            {'amount': '299.00', 'paid_at': '2026-03-01', 'payment_method': self.a.payment_method.pk},
        )
        self.assertRedirects(response, reverse('subscriptions:detail', args=[self.b.subscription.pk]))
        self.assertEqual(Payment.objects.count(), payments_before)

    def test_owner_cannot_be_forged_via_post(self):
        """Поле user в POST игнорируется: Б не может создать подписку от имени А."""
        data = subscription_post_data(self.catalog_service, title='test-подброшено', user=self.a.user.pk)
        self.client.post(reverse('subscriptions:create'), data)
        created = Subscription.objects.get(title='test-подброшено')
        self.assertEqual(created.user, self.b.user)

    def test_new_references_are_owned_by_creator(self):
        """Карта, тег и сервис, созданные Б с user/owner=А в POST, принадлежат Б."""
        forged = {'user': self.a.user.pk, 'owner': self.a.user.pk}
        self.client.post(reverse('subscriptions:paymentmethod-create'),
                         {'name': 'test-B-вторая-карта', 'kind': 'card', 'last4': '', **forged})
        self.client.post(reverse('subscriptions:tag-create'), {'name': 'test-B-второй-тег', **forged})
        self.client.post(reverse('subscriptions:service-create'),
                         {'name': 'test-B-второй-сервис', 'category': self.category.pk, 'website': '', **forged})
        self.assertEqual(PaymentMethod.objects.get(name='test-B-вторая-карта').user, self.b.user)
        self.assertEqual(Tag.objects.get(name='test-B-второй-тег').user, self.b.user)
        self.assertEqual(Service.objects.get(name='test-B-второй-сервис').owner, self.b.user)


class CatalogServiceProtectionTests(IsolationTestBase):
    """Сервисы общего каталога (owner = NULL) никто не может изменить или удалить."""

    def test_catalog_service_edit_and_delete_return_404_for_everyone(self):
        """GET и POST на изменение/удаление каталожного сервиса - 404 и для А, и для Б."""
        pk = self.catalog_service.pk
        endpoints = [
            Endpoint('редактирование', reverse('subscriptions:service-update', args=[pk]),
                     {'name': 'test-взломано', 'category': self.category.pk, 'website': ''}),
            Endpoint('удаление', reverse('subscriptions:service-delete', args=[pk])),
        ]
        for user in (self.a.user, self.b.user):
            self.client.force_login(user)
            for endpoint in endpoints:
                for method in ('get', 'post'):
                    with self.subTest(user=user.username, action=endpoint.label, method=method):
                        response = getattr(self.client, method)(endpoint.url, endpoint.post_data)
                        self.assertEqual(response.status_code, 404)
        self.catalog_service.refresh_from_db()
        self.assertEqual(self.catalog_service.name, 'test-Каталог-общий')
        self.assertIsNone(self.catalog_service.owner)


class AnonymousAccessTests(IsolationTestBase):
    """Гость не получает доступа ни к одной странице приложения подписок."""

    def setUp(self):
        self.client.logout()

    def all_endpoints(self):
        return collection_endpoints(self.catalog_service, self.category) + object_endpoints(
            self.a, self.catalog_service, self.category,
        )

    def test_get_redirects_to_login(self):
        """GET на любой защищённый URL - редирект на вход с ?next=."""
        for endpoint in self.all_endpoints():
            with self.subTest(endpoint.label, url=endpoint.url):
                response = self.client.get(endpoint.url)
                self.assertRedirects(response, login_redirect_url(endpoint.url), fetch_redirect_response=False)

    def test_post_redirects_to_login_and_changes_nothing(self):
        """POST на любой защищённый URL - редирект на вход, в БД ничего не создано и не изменено."""
        counts = lambda: [m.objects.count() for m in (Subscription, Payment, PaymentMethod, Tag, Service)]  # noqa: E731
        for endpoint in self.all_endpoints():
            with self.subTest(endpoint.label, url=endpoint.url):
                before, counts_before = snapshot(self.a.user), counts()
                response = self.client.post(endpoint.url, endpoint.post_data)
                self.assertRedirects(response, login_redirect_url(endpoint.url), fetch_redirect_response=False)
                self.assertEqual(snapshot(self.a.user), before)
                self.assertEqual(counts(), counts_before)
