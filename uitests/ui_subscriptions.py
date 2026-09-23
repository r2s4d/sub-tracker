"""Работа с подписками: создание, проверки формы, оплата, удаление. Кейсы 6-10."""

from datetime import date

import allure
import pytest
from playwright.sync_api import expect

pytestmark = pytest.mark.usefixtures('browser_window')


def open_first_subscription(page, live_server):
    """Открывает страницу первой подписки из списка."""
    page.goto(f'{live_server.url}/subscriptions/')
    page.locator('.subscription-row .ledger-title').first.click()
    page.wait_for_load_state('networkidle')


@allure.epic('Subscription Tracker')
@allure.feature('Подписки')
@allure.story('Создание')
@allure.severity(allure.severity_level.BLOCKER)
@allure.title('UI-06. Позитивный: новая подписка создаётся и появляется в списке')
@allure.description("""
Что делает: открывает форму добавления, выбирает сервис, вводит цену, тип оплаты
и дату начала, сохраняет.
Что проверяет: после сохранения открывается страница созданной подписки с введённой
ценой, а сама подписка появляется в общем списке. Основной сценарий работы с сервисом.
""")
def test_create_subscription_appears_in_list(page, live_server, user, login):
    login()

    with allure.step('Открыть форму добавления подписки'):
        page.goto(f'{live_server.url}/subscriptions/new/')

    with allure.step('Заполнить поля: сервис, цена, тип оплаты, дата начала'):
        page.select_option('#id_service', label='JetBrains')
        page.fill('#id_title', 'Тариф для UI-теста')
        page.fill('#id_price', '1234')
        page.select_option('#id_billing_type', 'monthly')
        page.fill('#id_start_date', date.today().strftime('%Y-%m-%d'))

    with allure.step('Сохранить форму'):
        page.click('main button[type="submit"]')
        page.wait_for_load_state('networkidle')

    with allure.step('Проверить, что открылась страница новой подписки'):
        expect(page.locator('body')).to_contain_text('Тариф для UI-теста')
        expect(page.locator('body')).to_contain_text('1 234')

    with allure.step('Проверить, что подписка видна в списке'):
        page.goto(f'{live_server.url}/subscriptions/')
        expect(page.locator('.subscription-row')).to_contain_text(['Тариф для UI-теста'])


@allure.epic('Subscription Tracker')
@allure.feature('Подписки')
@allure.story('Проверка формы')
@allure.severity(allure.severity_level.NORMAL)
@allure.title('UI-07. Негативный: отрицательная цена не сохраняется')
@allure.description("""
Что делает: заполняет форму подписки корректно, но ставит цену минус 100.
Что проверяет: форма возвращается с ошибкой под полем цены, подписка не создаётся.
Проверяется, что ограничение на неотрицательную цену доходит до интерфейса,
а не срабатывает только в базе.
""")
def test_negative_price_is_rejected(page, live_server, user, login):
    login()

    with allure.step('Открыть форму добавления подписки'):
        page.goto(f'{live_server.url}/subscriptions/new/')

    with allure.step('Ввести отрицательную цену и сохранить'):
        page.select_option('#id_service', label='Кинопоиск')
        page.fill('#id_price', '-100')
        page.select_option('#id_billing_type', 'monthly')
        page.fill('#id_start_date', date.today().strftime('%Y-%m-%d'))
        page.click('main button[type="submit"]')

    with allure.step('Проверить, что подписка не создана и показана ошибка'):
        expect(page).to_have_url(f'{live_server.url}/subscriptions/new/')
        expect(page.locator('.invalid-feedback').first).to_be_visible()


@allure.epic('Subscription Tracker')
@allure.feature('Подписки')
@allure.story('Проверка формы')
@allure.severity(allure.severity_level.NORMAL)
@allure.title('UI-08. Негативный: пробный период без даты окончания не сохраняется')
@allure.description("""
Что делает: выбирает тип оплаты «Пробный период», но не заполняет дату его окончания
и периодичность оплаты после него.
Что проверяет: форма показывает ошибки у обоих обязательных полей и не сохраняет
запись. Это правило важно: без даты окончания невозможно посчитать первое списание.
""")
def test_trial_without_end_date_is_rejected(page, live_server, user, login):
    login()

    with allure.step('Открыть форму и выбрать тип оплаты «Пробный период»'):
        page.goto(f'{live_server.url}/subscriptions/new/')
        page.select_option('#id_service', label='Кинопоиск')
        page.fill('#id_price', '399')
        page.select_option('#id_billing_type', 'trial')
        page.fill('#id_start_date', date.today().strftime('%Y-%m-%d'))

    with allure.step('Сохранить, не заполняя поля пробного периода'):
        page.click('main button[type="submit"]')

    with allure.step('Проверить, что форма вернулась с ошибками у обоих полей'):
        expect(page).to_have_url(f'{live_server.url}/subscriptions/new/')
        errors = page.locator('main .invalid-feedback')
        # Ошибок больше двух: поля проверяются и формой, и методом clean() модели.
        assert errors.count() >= 2, f'Ожидались ошибки у двух полей, найдено {errors.count()}'
        expect(page.locator('main')).to_contain_text('пробного периода')


@allure.epic('Subscription Tracker')
@allure.feature('Подписки')
@allure.story('Платежи')
@allure.severity(allure.severity_level.CRITICAL)
@allure.title('UI-09. Позитивный: отметка «оплачено» добавляет платёж в историю')
@allure.description("""
Что делает: открывает подписку и нажимает «Отметить оплату» с суммой и датой,
которые подставлены по умолчанию.
Что проверяет: появляется сообщение об успехе, а в истории платежей подписки
становится на одну запись больше. Так пользователь ведёт фактические расходы.
""")
def test_mark_paid_adds_payment(page, live_server, user, login):
    login()
    open_first_subscription(page, live_server)
    payments_before = page.locator('.subscription-payment').count()

    with allure.step('Заполнить дату списания и отметить оплату'):
        page.fill('input[name="paid_at"]', date.today().strftime('%Y-%m-%d'))
        page.click('main button:has-text("Отметить оплату")')
        page.wait_for_load_state('networkidle')

    with allure.step('Проверить сообщение об успехе'):
        expect(page.locator('body')).to_contain_text('записан')

    with allure.step('Проверить, что платежей стало больше'):
        assert page.locator('.subscription-payment').count() > payments_before


@allure.epic('Subscription Tracker')
@allure.feature('Подписки')
@allure.story('Удаление')
@allure.severity(allure.severity_level.NORMAL)
@allure.title('UI-10. Позитивный: удаление подписки спрашивает подтверждение и убирает её из списка')
@allure.description("""
Что делает: открывает подписку, нажимает удаление, читает предупреждение
и подтверждает действие.
Что проверяет: сначала показывается страница подтверждения с предупреждением,
что вместе с подпиской удалится история платежей, а после подтверждения
подписка исчезает из списка. Проверяется защита от случайного удаления.
""")
def test_delete_subscription_asks_confirmation(page, live_server, user, login):
    login()

    with allure.step('Открыть список и запомнить количество подписок'):
        page.goto(f'{live_server.url}/subscriptions/')
        rows_before = page.locator('.subscription-row').count()
        title = page.locator('.subscription-row .ledger-title').first.inner_text()

    with allure.step('Открыть подписку и нажать удаление'):
        page.locator('.subscription-row .ledger-title').first.click()
        page.click('main a:has-text("Удалить")')
        page.wait_for_load_state('networkidle')

    with allure.step('Проверить, что показана страница подтверждения'):
        expect(page.locator('h1')).to_contain_text('Удалить подписку?')
        expect(page.locator('body')).to_contain_text('история её платежей')

    with allure.step('Подтвердить удаление'):
        page.click('main button:has-text("Удалить")')
        page.wait_for_load_state('networkidle')

    with allure.step('Проверить, что подписка пропала из списка'):
        expect(page.locator('.subscription-row')).to_have_count(rows_before - 1)
        expect(page.locator('#subscription-results')).not_to_contain_text(title)
