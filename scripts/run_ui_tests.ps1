# Запуск UI-тестов и сборка отчёта Allure одной командой:
#
#   powershell -ExecutionPolicy Bypass -File scripts\run_ui_tests.ps1
#
# Что делает:
#   1. проверяет, что база данных поднята (docker compose up -d db);
#   2. прогоняет 15 UI-тестов в браузере Chromium;
#   3. собирает отчёт Allure и открывает его в браузере.
#
# Отчёту Allure нужна Java. Если её нет в PATH, берётся та, что поставляется
# с PyCharm: отдельно устанавливать ничего не надо.

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

$python = Join-Path $root '.venv\Scripts\python.exe'
if (-not (Test-Path $python)) { throw "Не найден интерпретатор $python" }

Write-Host 'Проверяю базу данных...' -ForegroundColor Cyan
docker compose up -d db | Out-Null

Write-Host 'Запускаю UI-тесты в браузере...' -ForegroundColor Cyan
& $python -m pytest uitests --alluredir=allure-results --clean-alluredir
$testsExitCode = $LASTEXITCODE

if (-not (Get-Command java -ErrorAction SilentlyContinue)) {
    $jbr = Get-ChildItem 'C:\Program Files\JetBrains' -Filter java.exe -Recurse -Depth 4 -ErrorAction SilentlyContinue |
           Select-Object -First 1
    if ($jbr) {
        $env:JAVA_HOME = Split-Path -Parent (Split-Path -Parent $jbr.FullName)
        $env:PATH = "$env:JAVA_HOME\bin;$env:PATH"
        Write-Host "Java взята из PyCharm: $env:JAVA_HOME" -ForegroundColor DarkGray
    } else {
        Write-Warning 'Java не найдена, отчёт Allure собрать нельзя. Результаты тестов лежат в allure-results.'
        exit $testsExitCode
    }
}

Write-Host 'Собираю отчёт Allure...' -ForegroundColor Cyan
npx --yes allure-commandline generate allure-results --clean -o allure-report

Write-Host 'Открываю отчёт...' -ForegroundColor Cyan
Start-Process powershell -ArgumentList '-NoProfile', '-Command', "npx --yes allure-commandline open `"$root\allure-report`""

exit $testsExitCode
