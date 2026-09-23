"""Обзор и живые фильтры. Кейсы 11-13.

Здесь проверяется то, что нельзя проверить без браузера: работа JavaScript,
то есть фильтры без перезагрузки страницы и раскрытие категории на диаграмме.
"""

import re

import allure
import pytest
from playwright.sync_api import expect

pytestmark = pytest.mark.usefixtures('browser_window')


@allure.epic('Subscription Tracker')
@allure.feature('Обзор')
@allure.story('Отображение')
@allure.severity(allure.severity_level.BLOCKER)
@allure.title('UI-11. Позитивный: обзор показывает месячную сумму и диаграмму по категориям')
@allure.description("""
Что делает: входит в систему и открывает обзор.
Что проверяет: на странице есть месячная сумма расходов, кольцевая диаграмма
действительно нарисована (у элемента canvas ненулевой размер, то есть Chart.js
отработал), и рядом с диаграммой есть текстовая легенда с категориями.
Последнее важно: цвет не должен быть единственным носителем смысла.
""")
def test_dashboard_shows_total_and_chart(page, live_server, user, login):
    login()

    with allure.step('Открыть обзор'):
        page.goto(f'{live_server.url}/subscriptions/dashboard/')
        page.wait_for_load_state('networkidle')

    with allure.step('Проверить заголовок с месячной суммой'):
        expect(page.locator('#hero-title')).to_contain_text('в месяц')

    with allure.step('Проверить, что кольцевая диаграмма нарисована'):
        canvas = page.locator('#chart-categories')
        expect(canvas).to_be_visible()
        box = canvas.bounding_box()
        assert box['width'] > 100 and box['height'] > 100, 'Диаграмма не отрисовалась'

    with allure.step('Проверить текстовую легенду рядом с диаграммой'):
        expect(page.locator('[data-legend] .legend-item').first).to_be_visible()

    allure.attach(page.screenshot(), name='Обзор', attachment_type=allure.attachment_type.PNG)


@allure.epic('Subscription Tracker')
@allure.feature('Мои подписки')
@allure.story('Фильтры')
@allure.severity(allure.severity_level.CRITICAL)
@allure.title('UI-12. Позитивный: фильтр по категории сужает список без перезагрузки страницы')
@allure.description("""
Что делает: открывает список подписок, выбирает категорию в выпадающем списке.
Что проверяет: список перерисовывается и показывает только подписки выбранной
категории, при этом страница не перезагружается (проверяется по тому, что объект
в памяти страницы сохраняется), а адрес в строке браузера обновляется,
то есть ссылкой с фильтром можно поделиться.
""")
def test_category_filter_updates_list_without_reload(page, live_server, user, login):
    login()

    with allure.step('Открыть список подписок'):
        page.goto(f'{live_server.url}/subscriptions/')
        expect(page.locator('.subscription-row')).to_have_count(3)

    with allure.step('Пометить страницу, чтобы заметить перезагрузку'):
        page.evaluate("window.__uiTestMark = 'не перезагружалась'")

    with allure.step('Выбрать категорию «Связь»'):
        page.select_option('#filter-category', label='Связь')
        expect(page.locator('.subscription-row')).to_have_count(1)

    with allure.step('Проверить, что остался только МегаФон'):
        expect(page.locator('.subscription-row')).to_contain_text(['МегаФон'])

    with allure.step('Проверить, что страница не перезагружалась и адрес обновился'):
        assert page.evaluate('window.__uiTestMark') == 'не перезагружалась'
        expect(page).to_have_url(re.compile(r'\?category='))


@allure.epic('Subscription Tracker')
@allure.feature('Обзор')
@allure.story('Диаграмма')
@allure.severity(allure.severity_level.NORMAL)
@allure.title('UI-13. Позитивный: клик по категории в легенде раскрывает её подписки')
@allure.description("""
Что делает: на обзоре нажимает на строку категории рядом с кольцевой диаграммой.
Что проверяет: раскрывается список подписок этой категории, то есть работает
интерактивность диаграммы. Повторный клик список сворачивает.
""")
def test_category_drilldown_opens_subscriptions(page, live_server, user, login):
    login()

    with allure.step('Открыть обзор'):
        page.goto(f'{live_server.url}/subscriptions/dashboard/')
        page.wait_for_load_state('networkidle')

    first_category = page.locator('[data-legend] .legend-item').first
    items = page.locator('#legend-items-0')

    with allure.step('Проверить, что подписки категории сначала скрыты'):
        expect(items).to_be_hidden()

    with allure.step('Нажать на категорию в легенде'):
        first_category.click()

    with allure.step('Проверить, что список подписок категории раскрылся'):
        expect(items).to_be_visible()

    with allure.step('Нажать ещё раз и проверить, что список свернулся'):
        first_category.click()
        expect(items).to_be_hidden()
