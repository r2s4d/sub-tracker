"""Data-миграция: фиксированный справочник категорий и стартовый каталог сервисов.

Почему данные в миграции, а не в фикстуре: категории — часть схемы приложения
(ТЗ, раздел 2), они должны появляться автоматически при `migrate` на любой
новой БД (локально, в тестах, на VPS), без ручного `loaddata`.

Модели берутся через apps.get_model, а не импортом из models.py: миграция
работает с «исторической» версией модели на момент 0001, поэтому не сломается,
если модели в будущем изменятся.
"""

from django.db import migrations

# (название, slug, HEX-цвет для круговой диаграммы).
# Порядок в списке задаёт sort_order: 10, 20, 30, ...
# Цвета приглушённые и хорошо различимые между собой.
CATEGORIES = [
    ('Развлечения', 'entertainment', '#E76F51'),  # коралловый
    ('Работа и инструменты', 'work-tools', '#4F7CAC'),  # стальной синий
    ('Музыка', 'music', '#9B5DE5'),  # фиолетовый
    ('Связь', 'mobile', '#2A9D8F'),  # бирюзовый
    ('Интернет, хостинг и серверы', 'internet-hosting', '#E9B949'),  # горчичный
    ('Здоровье и спорт', 'health-sport', '#6BAA3A'),  # травяной зелёный
    ('Прочее', 'other', '#8D99AE'),  # серо-голубой
]

# slug категории -> [(название сервиса, сайт), ...]
SERVICES = {
    'entertainment': [
        ('Кинопоиск', 'https://www.kinopoisk.ru/'),
        ('Иви', 'https://www.ivi.ru/'),
        ('Okko', 'https://okko.tv/'),
        ('Netflix', 'https://www.netflix.com/'),
        ('PlayStation Plus', 'https://www.playstation.com/ps-plus/'),
        ('Xbox Game Pass', 'https://www.xbox.com/xbox-game-pass'),
    ],
    'work-tools': [
        ('JetBrains', 'https://www.jetbrains.com/'),
        ('GitHub Copilot', 'https://github.com/features/copilot'),
        ('ChatGPT Plus', 'https://chatgpt.com/'),
        ('Claude Pro', 'https://claude.ai/'),
        ('Notion', 'https://www.notion.so/'),
        ('Figma', 'https://www.figma.com/'),
    ],
    'music': [
        ('Яндекс Музыка', 'https://music.yandex.ru/'),
        ('Spotify', 'https://www.spotify.com/'),
        ('Apple Music', 'https://music.apple.com/'),
        ('VK Музыка', 'https://vk.com/music'),
        ('Звук', 'https://zvuk.com/'),
    ],
    'mobile': [
        ('МегаФон', 'https://www.megafon.ru/'),
        ('Билайн', 'https://beeline.ru/'),
        ('МТС', 'https://www.mts.ru/'),
        ('Т2', 'https://t2.ru/'),
        ('Yota', 'https://www.yota.ru/'),
    ],
    'internet-hosting': [
        ('Ростелеком', 'https://rt.ru/'),
        ('Timeweb Cloud', 'https://timeweb.cloud/'),
        ('Selectel', 'https://selectel.ru/'),
        ('REG.RU', 'https://www.reg.ru/'),
        ('Beget', 'https://beget.com/'),
        ('DigitalOcean', 'https://www.digitalocean.com/'),
    ],
    'health-sport': [
        ('World Class', 'https://www.worldclass.ru/'),
        ('DDX Fitness', 'https://www.ddxfitness.ru/'),
        ('СберЗдоровье', 'https://sberhealth.ru/'),
        ('Strava', 'https://www.strava.com/'),
    ],
    'other': [
        ('Яндекс Плюс', 'https://plus.yandex.ru/'),
        ('iCloud+', 'https://www.icloud.com/'),
        ('Google One', 'https://one.google.com/'),
        ('Telegram Premium', 'https://telegram.org/'),
        ('Литрес', 'https://www.litres.ru/'),
    ],
}


def seed_catalog(apps, schema_editor):
    """Создаёт категории и каталог сервисов.

    update_or_create делает миграцию идемпотентной: повторный запуск
    не создаёт дубликатов, а лишь обновляет цвет/порядок/сайт.
    """
    Category = apps.get_model('subscriptions', 'Category')
    Service = apps.get_model('subscriptions', 'Service')

    categories = {}
    for index, (name, slug, color) in enumerate(CATEGORIES, start=1):
        category, _ = Category.objects.update_or_create(
            slug=slug,
            defaults={'name': name, 'color': color, 'sort_order': index * 10},
        )
        categories[slug] = category

    for slug, services in SERVICES.items():
        for name, website in services:
            # owner=None — запись общего каталога, видна всем пользователям.
            Service.objects.update_or_create(
                name=name,
                owner=None,
                defaults={'category': categories[slug], 'website': website},
            )


def unseed_catalog(apps, schema_editor):
    """Откат: удаляет только то, что создала эта миграция.

    Пользовательские сервисы (owner != NULL) не трогаем. Сначала сервисы,
    потом категории — FK Service.category защищён PROTECT.
    """
    Category = apps.get_model('subscriptions', 'Category')
    Service = apps.get_model('subscriptions', 'Service')

    service_names = [name for services in SERVICES.values() for name, _ in services]
    Service.objects.filter(owner__isnull=True, name__in=service_names).delete()
    Category.objects.filter(slug__in=[slug for _, slug, _ in CATEGORIES]).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('subscriptions', '0001_initial'),
    ]

    operations = [
        migrations.RunPython(seed_catalog, unseed_catalog),
    ]
