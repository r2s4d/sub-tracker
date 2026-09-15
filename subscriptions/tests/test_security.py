"""Граничные случаи ввода: регистрация, SQL-инъекции, XSS, CSRF, опасные ссылки.

Защита в проекте встроенная, эти тесты фиксируют, что она не отключена:
- ORM Django всегда передаёт значения в SQL параметрами, а не склейкой строк;
- шаблоны экранируют HTML по умолчанию, данные в JS передаются через json_script;
- формы валидируют имя пользователя, почту, адреса сайтов;
- POST без CSRF-токена отклоняется.
"""

from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse

from subscriptions.models import Category, Service, Subscription, Tag

from .utils import make_category, make_subscription, make_user

User = get_user_model()

XSS_SCRIPT = '<script>alert(1)</script>'
XSS_IMG = '<img src=x onerror=alert(1)>'
SQLI = "' OR '1'='1'; DROP TABLE auth_user; --"
STRONG_PASSWORD = 'Str0ng-pass-42'


class SignUpEdgeCaseTests(TestCase):
    url = reverse('signup')

    def signup(self, **overrides):
        data = {
            'username': 'valid_user',
            'email': 'valid@example.com',
            'password1': STRONG_PASSWORD,
            'password2': STRONG_PASSWORD,
        }
        data.update(overrides)
        return self.client.post(self.url, data)

    def assert_rejected(self, response, field):
        self.assertEqual(response.status_code, 200, 'форма должна вернуться с ошибкой, а не упасть')
        self.assertIn(field, response.context['form'].errors)
        self.assertFalse(User.objects.exclude(username__in=['existing']).exists())

    def test_username_with_html_rejected(self):
        """В имени пользователя допустимы только буквы, цифры и @ . + - _ - теги не пройдут."""
        self.assert_rejected(self.signup(username=XSS_SCRIPT), 'username')

    def test_username_with_sql_rejected(self):
        self.assert_rejected(self.signup(username=SQLI), 'username')

    def test_username_with_spaces_rejected(self):
        self.assert_rejected(self.signup(username='ivan petrov'), 'username')

    def test_username_too_long_rejected(self):
        self.assert_rejected(self.signup(username='a' * 151), 'username')

    def test_cyrillic_username_allowed(self):
        response = self.signup(username='Егор_42')
        self.assertEqual(response.status_code, 302)
        self.assertTrue(User.objects.filter(username='Егор_42').exists())

    def test_username_case_insensitive_duplicate_rejected(self):
        """Django запрещает «Egor» и «egor» как разных пользователей."""
        User.objects.create_user('existing', email='e@example.com', password=STRONG_PASSWORD)
        self.assert_rejected(self.signup(username='EXISTING', email='new@example.com'), 'username')

    def test_email_header_injection_rejected(self):
        """Перевод строки в почте мог бы добавить заголовок письма (Bcc) - валидатор его не пропускает."""
        self.assert_rejected(self.signup(email='victim@example.com\nBcc: spam@example.com'), 'email')

    def test_invalid_email_rejected(self):
        for email in ['not-an-email', 'a@', '@example.com', f'{XSS_IMG}@example.com']:
            with self.subTest(email=email):
                self.assert_rejected(self.signup(email=email), 'email')

    def test_weak_passwords_rejected(self):
        cases = {
            'short': 'Ab1!',
            'common': 'password',
            'numeric': '1234567890',
            'similar to username': 'valid_user1',
        }
        for reason, password in cases.items():
            with self.subTest(reason=reason):
                self.assert_rejected(self.signup(password1=password, password2=password), 'password2')

    def test_password_mismatch_rejected(self):
        self.assert_rejected(self.signup(password2=STRONG_PASSWORD + 'x'), 'password2')

    def test_empty_fields_rejected(self):
        response = self.signup(username='', email='', password1='', password2='')
        self.assertEqual(response.status_code, 200)
        self.assertTrue({'username', 'email', 'password1', 'password2'} <= set(response.context['form'].errors))

    def test_password_stored_as_hash(self):
        self.signup()
        user = User.objects.get(username='valid_user')
        self.assertNotEqual(user.password, STRONG_PASSWORD)
        self.assertTrue(user.password.startswith('pbkdf2_sha256$'))
        self.assertFalse(user.is_staff or user.is_superuser)

    def test_cannot_escalate_privileges_via_post(self):
        """Лишние поля в POST (is_staff, is_superuser) форма игнорирует."""
        self.signup(is_staff='on', is_superuser='on')
        user = User.objects.get(username='valid_user')
        self.assertFalse(user.is_staff or user.is_superuser)


class LoginInjectionTests(TestCase):
    def test_sql_injection_in_login_does_not_authenticate(self):
        User.objects.create_user('victim', password=STRONG_PASSWORD)
        response = self.client.post(reverse('login'), {'username': SQLI, 'password': SQLI})
        self.assertEqual(response.status_code, 200)
        self.assertNotIn('_auth_user_id', self.client.session)
        response = self.client.post(reverse('login'), {'username': "victim' --", 'password': 'x'})
        self.assertNotIn('_auth_user_id', self.client.session)
        self.assertTrue(User.objects.filter(username='victim').exists())

    def test_login_next_to_external_site_ignored(self):
        User.objects.create_user('victim', password=STRONG_PASSWORD)
        response = self.client.post(
            f"{reverse('login')}?next=https://evil.example/",
            {'username': 'victim', 'password': STRONG_PASSWORD},
        )
        self.assertNotIn('evil.example', response['Location'])


class StoredXssTests(TestCase):
    """Данные пользователя с HTML выводятся как текст на всех страницах."""

    def setUp(self):
        self.user = make_user('xss')
        self.client.force_login(self.user)
        category = make_category('xss')
        self.service = Service.objects.create(name=XSS_IMG, category=category, owner=self.user)
        self.subscription = make_subscription(
            self.user, self.service, title=XSS_SCRIPT, notes=XSS_SCRIPT, start_date=date(2026, 9, 1),
        )
        self.subscription.tags.add(Tag.objects.create(user=self.user, name=XSS_IMG[:32]))

    def test_pages_escape_user_content(self):
        pages = {
            'список': reverse('subscriptions:list'),
            'фильтр списка': reverse('subscriptions:list') + '?status=all',
            'карточка': reverse('subscriptions:detail', args=[self.subscription.pk]),
            'редактирование': reverse('subscriptions:update', args=[self.subscription.pk]),
            'обзор': reverse('subscriptions:dashboard'),
            'сервисы': reverse('subscriptions:service-list'),
            'поиск сервиса': reverse('subscriptions:service-list') + '?q=' + XSS_SCRIPT,
            'теги': reverse('subscriptions:tag-list'),
        }
        for name, url in pages.items():
            with self.subTest(page=name):
                response = self.client.get(url)
                self.assertEqual(response.status_code, 200)
                html = response.content.decode()
                self.assertNotIn(XSS_SCRIPT, html)
                self.assertNotIn(XSS_IMG, html)

    def test_list_partial_escapes_user_content(self):
        response = self.client.get(reverse('subscriptions:list'), HTTP_X_PARTIAL='results')
        self.assertNotIn(XSS_SCRIPT, response.content.decode())
        self.assertIn('&lt;script&gt;', response.content.decode())

    def test_dashboard_chart_json_cannot_break_out_of_script(self):
        """json_script экранирует «<», поэтому название категории не закроет тег <script>."""
        Category.objects.filter(slug='test-category-xss').update(name='</script><script>alert(1)</script>')
        response = self.client.get(reverse('subscriptions:dashboard'))
        self.assertNotIn('</script><script>alert(1)', response.content.decode())


class QueryParameterInjectionTests(TestCase):
    def setUp(self):
        self.user = make_user('params')
        self.client.force_login(self.user)
        category = make_category('params')
        make_subscription(self.user, Service.objects.create(name='test-сервис', category=category))

    def test_filters_with_sql_do_not_break_or_leak(self):
        url = reverse('subscriptions:list')
        for params in [
            {'category': SQLI}, {'tag': '1 OR 1=1'}, {'tag': SQLI}, {'status': XSS_SCRIPT},
            {'billing_type': "monthly' OR '1'='1"},
        ]:
            with self.subTest(params=params):
                response = self.client.get(url, params)
                self.assertEqual(response.status_code, 200)
                self.assertNotIn(XSS_SCRIPT, response.content.decode())
        self.assertTrue(User.objects.filter(username='params').exists())

    def test_non_numeric_ids_in_urls_are_404(self):
        response = self.client.get('/subscriptions/1%20OR%201=1/')
        self.assertEqual(response.status_code, 404)


class DangerousInputTests(TestCase):
    def setUp(self):
        self.user = make_user('danger')
        self.client.force_login(self.user)
        self.category = make_category('danger')

    def test_javascript_url_rejected_for_service_website(self):
        """В ссылку «сайт» нельзя подставить javascript: - URLField пропускает только http(s)/ftp(s)."""
        response = self.client.post(reverse('subscriptions:service-create'), {
            'name': 'test-опасный', 'category': self.category.pk, 'website': 'javascript:alert(1)',
        })
        self.assertEqual(response.status_code, 200)
        self.assertIn('website', response.context['form'].errors)
        self.assertFalse(Service.objects.filter(name='test-опасный').exists())

    def test_huge_and_negative_prices_rejected(self):
        service = Service.objects.create(name='test-цена', category=self.category)
        for price in ['-1', '99999999999', 'NaN', '1e10', 'abc']:
            with self.subTest(price=price):
                response = self.client.post(reverse('subscriptions:create'), {
                    'service': service.pk, 'price': price, 'billing_type': 'monthly', 'start_date': '2026-09-01',
                })
                self.assertEqual(response.status_code, 200)
                self.assertIn('price', response.context['form'].errors)
        self.assertFalse(Subscription.objects.exists())

    def test_invalid_dates_rejected(self):
        service = Service.objects.create(name='test-дата', category=self.category)
        # «31.12.2026» валидна: при русской локали Django принимает и формат ДД.ММ.ГГГГ
        for start in ['2026-02-30', '32.12.2026', "2026-01-01' OR 1=1"]:
            with self.subTest(start=start):
                response = self.client.post(reverse('subscriptions:create'), {
                    'service': service.pk, 'price': '100', 'billing_type': 'monthly', 'start_date': start,
                })
                self.assertIn('start_date', response.context['form'].errors)

    def test_budget_negative_rejected(self):
        response = self.client.post(reverse('profile'), {
            'notification_email': '', 'notify_days_before': '-5', 'monthly_budget': '-100',
        })
        self.assertEqual(response.status_code, 200)
        self.assertIn('notify_days_before', response.context['form'].errors)


class CsrfTests(TestCase):
    """POST без CSRF-токена отклоняется (чужой сайт не сможет отправить форму от имени пользователя)."""

    def setUp(self):
        self.client = Client(enforce_csrf_checks=True)

    def test_signup_without_token_forbidden(self):
        response = self.client.post(reverse('signup'), {
            'username': 'csrf', 'email': 'csrf@example.com', 'password1': STRONG_PASSWORD, 'password2': STRONG_PASSWORD,
        })
        self.assertEqual(response.status_code, 403)
        self.assertFalse(User.objects.filter(username='csrf').exists())

    def test_delete_without_token_forbidden(self):
        user = make_user('csrf_owner')
        subscription = make_subscription(
            user, Service.objects.create(name='test-csrf', category=make_category('csrf')), price=Decimal('1'),
        )
        self.client.force_login(user)
        response = self.client.post(reverse('subscriptions:delete', args=[subscription.pk]))
        self.assertEqual(response.status_code, 403)
        self.assertTrue(Subscription.objects.filter(pk=subscription.pk).exists())
