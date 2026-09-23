"""Разграничение доступа. Кейсы 14-15.

Главное требование проекта: пользователь не должен видеть чужие данные
и не должен попадать на закрытые страницы без входа.
"""

import re

import allure
import pytest
from playwright.sync_api import expect

pytestmark = pytest.mark.usefixtures('browser_window')


@allure.epic('Subscription Tracker')
@allure.feature('Разграничение доступа')
@allure.story('Чужие данные')
@allure.severity(allure.severity_level.BLOCKER)
@allure.title('UI-14. Негативный: чужая подписка по прямой ссылке отдаёт страницу 404')
@allure.description("""
Что делает: входит под одним пользователем и вручную открывает адрес подписки,
которая принадлежит другому пользователю.
Что проверяет: открывается страница 404, содержимое чужой подписки не показывается.
Ответ именно 404, а не 403: посторонний не должен узнать даже то, что запись
с таким номером существует.
""")
def test_foreign_subscription_returns_404(page, live_server, user, other_user, login):
    stranger, foreign_subscription = other_user
    login()

    with allure.step(f'Открыть чужую подписку по прямому адресу (номер {foreign_subscription.pk})'):
        response = page.goto(f'{live_server.url}/subscriptions/{foreign_subscription.pk}/')

    with allure.step('Проверить код ответа 404'):
        assert response.status == 404, f'Ожидался 404, получен {response.status}'

    with allure.step('Проверить, что данные чужой подписки не показаны'):
        expect(page.locator('body')).not_to_contain_text('299')

    allure.attach(page.screenshot(), name='Страница 404', attachment_type=allure.attachment_type.PNG)


@allure.epic('Subscription Tracker')
@allure.feature('Разграничение доступа')
@allure.story('Вход обязателен')
@allure.severity(allure.severity_level.CRITICAL)
@allure.title('UI-15. Негативный: список подписок без входа перенаправляет на форму входа')
@allure.description("""
Что делает: без входа в систему открывает адрес списка подписок.
Что проверяет: вместо данных открывается форма входа, а адрес запрошенной страницы
сохраняется, чтобы после входа вернуть человека туда, куда он шёл.
""")
def test_anonymous_user_is_redirected_to_login(page, live_server, catalog):
    with allure.step('Открыть список подписок без входа'):
        page.goto(f'{live_server.url}/subscriptions/')

    with allure.step('Проверить, что открылась форма входа'):
        expect(page).to_have_url(re.compile(r'/accounts/login/'))
        expect(page.locator('#id_password')).to_be_visible()

    with allure.step('Проверить, что запрошенный адрес запомнен для возврата'):
        expect(page).to_have_url(re.compile(r'next=/subscriptions/'))
