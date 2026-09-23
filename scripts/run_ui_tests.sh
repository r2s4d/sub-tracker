#!/usr/bin/env bash
# Запуск UI-тестов и сборка отчёта Allure одной командой (macOS и Linux):
#
#   ./scripts/run_ui_tests.sh
#
# Ключи:
#   --headed      показать окно браузера (по умолчанию тесты идут в фоне, окна нет)
#   --open-only   не запускать тесты, а открыть последний собранный отчёт
#   --no-open     собрать отчёт, но не открывать его в браузере
#
# Версия для Windows: scripts\run_ui_tests.ps1
set -euo pipefail

cd "$(dirname "$0")/.."
ROOT=$(pwd)
RESULTS="$ROOT/allure-results"
REPORT="$ROOT/allure-report"

HEADED=""
OPEN_ONLY=""
NO_OPEN=""
for arg in "$@"; do
    case "$arg" in
        --headed) HEADED="--headed" ;;
        --open-only) OPEN_ONLY=1 ;;
        --no-open) NO_OPEN=1 ;;
        *) echo "Неизвестный ключ: $arg"; exit 2 ;;
    esac
done

# Интерпретатор из окружения проекта: на macOS и Linux это .venv/bin/python,
# на Windows (Git Bash) .venv/Scripts/python.exe. Системный python не подходит:
# в нём нет ни Django, ни pytest.
if [ -x "$ROOT/.venv/bin/python" ]; then
    PYTHON="$ROOT/.venv/bin/python"
elif [ -x "$ROOT/.venv/Scripts/python.exe" ]; then
    PYTHON="$ROOT/.venv/Scripts/python.exe"
else
    echo "Не найдено окружение .venv. Создайте его:"
    echo "  python3 -m venv .venv && .venv/bin/python -m pip install -r requirements-dev.txt"
    exit 1
fi

find_java() {
    if [ -n "${JAVA_HOME:-}" ] && [ -x "$JAVA_HOME/bin/java" ]; then return 0; fi
    if command -v java >/dev/null 2>&1; then return 0; fi
    # Java, поставляемая вместе с продуктами JetBrains: ставить отдельно не нужно
    for candidate in \
        /Applications/PyCharm.app/Contents/jbr/Contents/Home \
        /Applications/PyCharm\ Community\ Edition.app/Contents/jbr/Contents/Home \
        /Applications/IntelliJ\ IDEA.app/Contents/jbr/Contents/Home \
        "$HOME/Library/Application Support/JetBrains/Toolbox/apps"/*/jbr/Contents/Home \
        "/c/Program Files/JetBrains"/*/jbr
    do
        if [ -x "$candidate/bin/java" ]; then
            export JAVA_HOME="$candidate"
            export PATH="$JAVA_HOME/bin:$PATH"
            echo "Java взята из JetBrains: $JAVA_HOME"
            return 0
        fi
    done
    if /usr/libexec/java_home >/dev/null 2>&1; then
        JAVA_HOME=$(/usr/libexec/java_home)
        export JAVA_HOME
        export PATH="$JAVA_HOME/bin:$PATH"
        return 0
    fi
    return 1
}

if [ -z "$OPEN_ONLY" ]; then
    echo "Проверяю зависимости..."
    if ! "$PYTHON" -c "import django, pytest, allure_commons" >/dev/null 2>&1; then
        echo "В окружении не хватает пакетов. Установите их:"
        echo "  $PYTHON -m pip install -r requirements-dev.txt"
        echo "  $PYTHON -m playwright install chromium"
        exit 1
    fi

    echo "Проверяю базу данных..."
    docker compose up -d db >/dev/null

    if [ -n "$HEADED" ]; then
        echo "Запускаю UI-тесты с видимым окном браузера..."
    else
        echo "Запускаю UI-тесты в фоновом режиме (окно браузера не открывается)..."
    fi
    set +e
    "$PYTHON" -m pytest uitests --alluredir="$RESULTS" --clean-alluredir $HEADED
    TESTS_EXIT=$?
    set -e
else
    TESTS_EXIT=0
fi

if ! find_java; then
    echo "Java не найдена, отчёт Allure собрать нельзя. Данные прогона лежат в $RESULTS"
    echo "Поставить Java: brew install --cask temurin"
    exit $TESTS_EXIT
fi

if [ -z "$OPEN_ONLY" ]; then
    echo "Собираю отчёт Allure..."
    npx --yes allure-commandline generate "$RESULTS" --clean -o "$REPORT"
fi

if [ ! -f "$REPORT/index.html" ]; then
    echo "Отчёт не найден в $REPORT. Запустите скрипт без ключа --open-only."
    exit $TESTS_EXIT
fi

echo "Отчёт собран: $REPORT"

if [ -n "$NO_OPEN" ]; then
    echo "Открыть позже: ./scripts/run_ui_tests.sh --open-only"
    exit $TESTS_EXIT
fi

echo "Открываю отчёт в браузере. Чтобы закрыть, нажмите Ctrl+C."
npx --yes allure-commandline open "$REPORT"

exit $TESTS_EXIT
