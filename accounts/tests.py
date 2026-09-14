from django.contrib.auth import get_user_model
from django.test import TestCase

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
