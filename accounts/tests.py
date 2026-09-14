from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from .models import UserProfile

User = get_user_model()


class UserProfileSignalTests(TestCase):
    def test_profile_created_with_user(self):
        """При создании пользователя сигнал создаёт ему профиль (связь 1:1)."""
        user = User.objects.create_user('alice', email='alice@example.com', password='pass12345')
        self.assertTrue(UserProfile.objects.filter(user=user).exists())
        self.assertEqual(user.profile.notify_days_before, 3)

    def test_profile_not_duplicated_on_user_save(self):
        """Повторное сохранение пользователя не создаёт второй профиль."""
        user = User.objects.create_user('bob', password='pass12345')
        user.first_name = 'Bob'
        user.save()
        self.assertEqual(UserProfile.objects.filter(user=user).count(), 1)


class EffectiveEmailTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('carol', email='carol@example.com', password='pass12345')

    def test_falls_back_to_account_email(self):
        """Без почты для уведомлений используется почта аккаунта."""
        self.assertEqual(self.user.profile.effective_email, 'carol@example.com')

    def test_prefers_notification_email(self):
        """Почта для уведомлений имеет приоритет над почтой аккаунта."""
        profile = self.user.profile
        profile.notification_email = 'notify@example.com'
        profile.save()
        profile.refresh_from_db()
        self.assertEqual(profile.effective_email, 'notify@example.com')


class SignUpViewTests(TestCase):
    url = reverse('signup')

    def test_signup_creates_user_and_logs_in(self):
        response = self.client.post(self.url, {
            'username': 'dave',
            'email': 'Dave@Example.com',
            'password1': 'Str0ng-pass-42',
            'password2': 'Str0ng-pass-42',
        })
        self.assertRedirects(response, reverse('home'), fetch_redirect_response=False)
        user = User.objects.get(username='dave')
        self.assertEqual(user.email, 'dave@example.com')
        self.assertEqual(int(self.client.session['_auth_user_id']), user.pk)

    def test_signup_rejects_duplicate_email(self):
        User.objects.create_user('erin', email='erin@example.com', password='pass12345')
        response = self.client.post(self.url, {
            'username': 'erin2',
            'email': 'ERIN@example.com',
            'password1': 'Str0ng-pass-42',
            'password2': 'Str0ng-pass-42',
        })
        self.assertEqual(response.status_code, 200)
        self.assertFormError(response.context['form'], 'email', 'Аккаунт с этой почтой уже есть.')

    def test_authenticated_user_is_redirected(self):
        user = User.objects.create_user('frank', password='pass12345')
        self.client.force_login(user)
        self.assertRedirects(self.client.get(self.url), reverse('home'), fetch_redirect_response=False)


class LoginLogoutTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('grace', password='pass12345')

    def test_login_page_renders(self):
        self.assertEqual(self.client.get(reverse('login')).status_code, 200)

    def test_login_and_logout(self):
        response = self.client.post(reverse('login'), {'username': 'grace', 'password': 'pass12345'})
        self.assertRedirects(response, reverse('home'), fetch_redirect_response=False)
        response = self.client.post(reverse('logout'))
        self.assertRedirects(response, reverse('login'), fetch_redirect_response=False)
        self.assertNotIn('_auth_user_id', self.client.session)

    def test_home_redirects_guest_to_login(self):
        self.assertRedirects(self.client.get(reverse('home')), reverse('login'), fetch_redirect_response=False)


class ProfileViewTests(TestCase):
    url = reverse('profile')

    def setUp(self):
        self.user = User.objects.create_user('heidi', email='heidi@example.com', password='pass12345')
        self.other = User.objects.create_user('ivan', email='ivan@example.com', password='pass12345')

    def test_requires_login(self):
        response = self.client.get(self.url)
        self.assertRedirects(response, f"{reverse('login')}?next={self.url}", fetch_redirect_response=False)

    def test_updates_only_own_profile(self):
        """В URL нет pk: отредактировать можно только свой профиль."""
        self.client.force_login(self.user)
        response = self.client.post(self.url, {
            'notification_email': 'work@example.com',
            'notify_days_before': 5,
            'monthly_budget': '3500.00',
        })
        self.assertRedirects(response, self.url)
        self.user.profile.refresh_from_db()
        self.other.profile.refresh_from_db()
        self.assertEqual(self.user.profile.notification_email, 'work@example.com')
        self.assertEqual(self.other.profile.notification_email, '')
