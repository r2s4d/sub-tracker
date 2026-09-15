"""Новые цвета категорий для диаграмм дашборда.

Исходная палитра из 0002 не прошла проверку на различимость: горчичный был
слишком светлым, стальной синий и серо-голубой читались как серые, а для людей
с дальтонизмом соседние цвета сливались. Новая палитра проверена валидатором
(светлота, насыщенность, различимость при протанопии/дейтеранопии, контраст).
Цвета, контраст которых с белым фоном ниже 3:1, всегда сопровождаются подписью
и суммой в легенде - цвет не единственный носитель информации.
"""

from django.db import migrations

NEW_COLORS = {
    'entertainment': '#EB6834',
    'work-tools': '#2A78D6',
    'music': '#4A3AA7',
    'mobile': '#1BAF7A',
    'internet-hosting': '#EDA100',
    'health-sport': '#008300',
    'other': '#E87BA4',
}

OLD_COLORS = {
    'entertainment': '#E76F51',
    'work-tools': '#4F7CAC',
    'music': '#9B5DE5',
    'mobile': '#2A9D8F',
    'internet-hosting': '#E9B949',
    'health-sport': '#6BAA3A',
    'other': '#8D99AE',
}


def set_colors(colors):
    def apply(apps, schema_editor):
        Category = apps.get_model('subscriptions', 'Category')
        for slug, color in colors.items():
            Category.objects.filter(slug=slug).update(color=color)
    return apply


class Migration(migrations.Migration):
    dependencies = [
        ('subscriptions', '0002_seed_categories_and_services'),
    ]

    operations = [
        migrations.RunPython(set_colors(NEW_COLORS), set_colors(OLD_COLORS)),
    ]
