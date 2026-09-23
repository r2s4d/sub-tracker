# Запуск UI-тестов и сборка отчёта Allure одной командой:
#
#   powershell -ExecutionPolicy Bypass -File scripts\run_ui_tests.ps1
#
# Ключи:
#   -Headed     показать окно браузера (по умолчанию тесты идут в фоне, окна нет)
#   -OpenOnly   не запускать тесты, а открыть последний собранный отчёт
#   -NoOpen     собрать отчёт, но не открывать его в браузере
#
# Что делает по умолчанию:
#   1. проверяет, что база данных поднята (docker compose up -d db);
#   2. прогоняет 15 UI-тестов в браузере Chromium;
#   3. собирает отчёт Allure в папку allure-report и открывает его в браузере.
#
# Отчёту Allure нужна Java. Если её нет в PATH, берётся та, что поставляется
# с PyCharm: отдельно устанавливать ничего не надо.

[CmdletBinding()]
param(
    [switch]$Headed,
    [switch]$OpenOnly,
    [switch]$NoOpen
)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

$resultsDir = Join-Path $root 'allure-results'
$reportDir = Join-Path $root 'allure-report'
$testsExitCode = 0

function Use-Java {
    if (Get-Command java -ErrorAction SilentlyContinue) { return $true }
    $jbr = Get-ChildItem 'C:\Program Files\JetBrains' -Filter java.exe -Recurse -Depth 4 -ErrorAction SilentlyContinue |
           Select-Object -First 1
    if (-not $jbr) { return $false }
    # java.exe лежит в <JAVA_HOME>\bin, поэтому поднимаемся на два уровня вверх
    $env:JAVA_HOME = Split-Path -Parent (Split-Path -Parent $jbr.FullName)
    $env:PATH = "$env:JAVA_HOME\bin;$env:PATH"
    Write-Host "Java взята из PyCharm: $env:JAVA_HOME" -ForegroundColor DarkGray
    return $true
}

if (-not $OpenOnly) {
    $python = Join-Path $root '.venv\Scripts\python.exe'
    if (-not (Test-Path $python)) { throw "Не найден интерпретатор $python" }

    Write-Host 'Проверяю базу данных...' -ForegroundColor Cyan
    docker compose up -d db | Out-Null

    $pytestArgs = @('-m', 'pytest', 'uitests', '--alluredir', $resultsDir, '--clean-alluredir')
    if ($Headed) {
        $pytestArgs += '--headed'
        Write-Host 'Запускаю UI-тесты с видимым окном браузера...' -ForegroundColor Cyan
    } else {
        Write-Host 'Запускаю UI-тесты в фоновом режиме (окно браузера не открывается)...' -ForegroundColor Cyan
    }

    & $python @pytestArgs
    $testsExitCode = $LASTEXITCODE
}

if (-not (Use-Java)) {
    Write-Warning "Java не найдена, отчёт Allure собрать нельзя. Данные прогона лежат в $resultsDir"
    exit $testsExitCode
}

if (-not $OpenOnly) {
    Write-Host 'Собираю отчёт Allure...' -ForegroundColor Cyan
    npx --yes allure-commandline generate $resultsDir --clean -o $reportDir
}

if (-not (Test-Path (Join-Path $reportDir 'index.html'))) {
    Write-Warning "Отчёт не найден в $reportDir. Запустите скрипт без ключа -OpenOnly."
    exit $testsExitCode
}

Write-Host "Отчёт собран: $reportDir" -ForegroundColor Green

if ($NoOpen) {
    Write-Host 'Открыть позже: powershell -File scripts\run_ui_tests.ps1 -OpenOnly' -ForegroundColor DarkGray
    exit $testsExitCode
}

# allure open поднимает локальный сервер и сам открывает вкладку браузера.
# Окно остаётся открытым, пока смотрите отчёт; закрытие окна останавливает сервер.
Write-Host 'Открываю отчёт в браузере. Чтобы закрыть, закройте появившееся окно.' -ForegroundColor Cyan
npx --yes allure-commandline open $reportDir

exit $testsExitCode
