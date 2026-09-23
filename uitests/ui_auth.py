"""Вход, регистрация и выход. Кейсы 1-5."""

import re

import allure
import pytest
from playwright.sync_api import expect

from .conftest import PASSWORD

pytestmark = pytest.mark.usefixtures('browser_window')


@allure.epic('Subscription Tracker')
@allure.feature('Авторизация')
@allure.story('Регистрация')
@allure.severity(allure.severity_level.CRITICAL)
@allure.title('UI-01. Позитивный: регистрация нового пользователя открывает обзор')
@allure.description("""
Что делает: открывает страницу регистрации, заполняет имя, почту и пароль дважды, отправляет форму.
Что проверяет: после отправки пользователь сразу авторизован, попадает на обзор,
а в шапке видно его имя. Проверяется штатный вход нового человека в систему.
""")
def test_signup_creates_account_and_logs_in(page, live_server, catalog):
    with allure.step('Открыть страницу регистрации'):
        page.goto(f'{live_server.url}/accounts/signup/')

    with allure.step('Заполнить форму и отправить'):
        page.fill('#id_username', 'novichok')
        page.fill('#id_email', 'novichok@example.com')
        page.fill('#id_password1', 'Sub-Tracker-2026')
        page.fill('#id_password2', 'Sub-Tracker-2026')
        page.click('button[type="submit"]')

    with allure.step('Проверить, что открылся обзор и пользователь авторизован'):
        expect(page).to_have_url(f'{live_server.url}/subscriptions/dashboard/')
        expect(page.locator('body')).to_contain_text('novichok')


@allure.epic('Subscription Tracker')
@allure.feature('Авторизация')
@allure.story('Регистрация')
@allure.severity(allure.severity_level.NORMAL)
@allure.title('UI-02. Негативный: регистрация с занятой почтой отклоняется')
@allure.description("""
Что делает: пробует зарегистрировать второго пользователя на почту, которая уже занята.
Что проверяет: форма не отправляется, пользователь остаётся на странице регистрации
и видит понятную ошибку. Второй аккаунт с той же почтой не создаётся.
""")
def test_signup_with_taken_email_shows_error(page, live_server, user):
    with allure.step('Открыть страницу регистрации'):
        page.goto(f'{live_server.url}/accounts/signup/')

    with allure.step('Ввести почту уже существующего пользователя'):
        page.fill('#id_username', 'dvoynik')
        page.fill('#id_email', user.email)
        page.fill('#id_password1', 'Sub-Tracker-2026')
        page.fill('#id_password2', 'Sub-Tracker-2026')
        page.click('button[type="submit"]')

    with allure.step('Проверить, что показана ошибка и регистрация не прошла'):
        expect(page).to_have_url(f'{live_server.url}/accounts/signup/')
        expect(page.locator('.invalid-feedback')).to_contain_text('Аккаунт с этой почтой уже есть')


@allure.epic('Subscription Tracker')
@allure.feature('Авторизация')
@allure.story('Вход')
@allure.severity(allure.severity_level.BLOCKER)
@allure.title('UI-03. Позитивный: вход с верным паролем открывает обзор')
@allure.description("""
Что делает: заполняет форму входа именем и паролем существующего пользователя.
Что проверяет: происходит переход на обзор, на странице видны данные именно этого
пользователя (его подписки). Это основной сценарий, без которого недоступно всё остальное.
""")
def test_login_with_valid_password(page, live_server, user):
    with allure.step('Открыть страницу входа'):
        page.goto(f'{live_server.url}/accounts/login/')

    with allure.step('Ввести верные имя пользователя и пароль'):
        page.fill('#id_username', 'tester')
        page.fill('#id_password', PASSWORD)
        page.click('button[type="submit"]')

    with allure.step('Проверить, что открылся обзор с подписками пользователя'):
        expect(page).to_have_url(f'{live_server.url}/subscriptions/dashboard/')
        expect(page.locator('#hero-title')).to_be_visible()


@allure.epic('Subscription Tracker')
@allure.feature('Авторизация')
@allure.story('Вход')
@allure.severity(allure.severity_level.CRITICAL)
@allure.title('UI-04. Негативный: вход с неверным паролем не пускает в систему')
@allure.description("""
Что делает: вводит существующее имя пользователя и неправильный пароль.
Что проверяет: система остаётся на странице входа, показывает сообщение об ошибке
и не раскрывает, что именно неверно, имя или пароль. Обзор при этом недоступен.
""")
def test_login_with_wrong_password_is_rejected(page, live_server, user):
    with allure.step('Открыть страницу входа'):
        page.goto(f'{live_server.url}/accounts/login/')

    with allure.step('Ввести неверный пароль'):
        page.fill('#id_username', 'tester')
        page.fill('#id_password', 'sovsem-ne-tot-parol')
        page.click('button[type="submit"]')

    with allure.step('Проверить, что вход не выполнен и показана ошибка'):
        expect(page).to_have_url(f'{live_server.url}/accounts/login/')
        expect(page.locator('.flash-error')).to_be_visible()

    with allure.step('Проверить, что обзор остаётся недоступен'):
        page.goto(f'{live_server.url}/subscriptions/dashboard/')
        expect(page).to_have_url(re.compile(r'/accounts/login/'))


@allure.epic('Subscription Tracker')
@allure.feature('Авторизация')
@allure.story('Выход')
@allure.severity(allure.severity_level.NORMAL)
@allure.title('UI-05. Негативный: после выхода обзор снова недоступен')
@allure.description("""
Что делает: входит в систему, нажимает выход, затем пытается открыть обзор по прямому адресу.
Что проверяет: сессия действительно завершена, а не просто скрыта ссылка в меню:
попытка вернуться на защищённую страницу ведёт на форму входа.
""")
def test_logout_closes_access_to_dashboard(page, live_server, user, login):
    login()

    with allure.step('Выйти из аккаунта'):
        page.click('aside button:has-text("Выйти")')
        page.wait_for_load_state('networkidle')

    with allure.step('Попробовать открыть обзор по прямому адресу'):
        page.goto(f'{live_server.url}/subscriptions/dashboard/')

    with allure.step('Проверить, что открылась форма входа'):
        expect(page).to_have_url(re.compile(r'/accounts/login/'))
