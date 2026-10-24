# Build a self-contained Windows version and its installer (Setup .exe). Run on Windows 10/11 x64:
#
#   powershell -ExecutionPolicy Bypass -File scripts\build_windows.ps1              # with the speech model
#   powershell -ExecutionPolicy Bypass -File scripts\build_windows.ps1 -NoModel     # model downloaded on first start
#   powershell -ExecutionPolicy Bypass -File scripts\build_windows.ps1 -NoInstaller # only the program folder
#
# Needs 64-bit Python 3.11–3.14 (python.org; another one can be chosen with $env:PYTHON = "C:\path\python.exe") and Inno Setup 6 for the installer
# (https://jrsoftware.org/isinfo.php or: winget install JRSoftware.InnoSetup).
# Output: dist\Local Audiobook Reader\ and dist\Local-Audiobook-Reader-<ver>-Windows-Setup.exe
param(
    [switch]$NoModel,
    [switch]$NoInstaller
)
$ErrorActionPreference = "Stop"
# Ukrainian messages: make Python and the console use UTF-8 instead of the legacy code page (e.g. cp1252).
$env:PYTHONUTF8 = "1"
$env:PYTHONIOENCODING = "utf-8"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

# Runs a program and stops the build if it fails. A plain function (no param block), so arguments
# such as "-m" are passed through to the program instead of being parsed by PowerShell.
function Invoke-Checked {
    $exe = $args[0]
    $rest = @($args | Select-Object -Skip 1)  # always an array, even for a single argument
    & $exe @rest
    if ($LASTEXITCODE -ne 0) { throw "Команда завершилася з помилкою ($LASTEXITCODE): $exe $rest" }
}

$VenvPy = Join-Path $Root ".venv\Scripts\python.exe"
if (-not (Test-Path $VenvPy)) {
    if ($env:PYTHON) { Invoke-Checked $env:PYTHON -m venv .venv }
    elseif (Get-Command py -ErrorAction SilentlyContinue) { Invoke-Checked py -3 -m venv .venv }
    else { Invoke-Checked python -m venv .venv }
}
Write-Host "Python: $(& $VenvPy -c 'import sys, platform; print(sys.version.split()[0], platform.machine())')"
Invoke-Checked $VenvPy -m pip install --quiet --upgrade pip
Invoke-Checked $VenvPy -m pip install --quiet -r requirements.txt -r requirements-build.txt
$Version = (& $VenvPy -c "import tomllib; print(tomllib.load(open('pyproject.toml', 'rb'))['project']['version'])").Trim()
$AppName = "Local Audiobook Reader"

New-Item -ItemType Directory -Force -Path assets, build | Out-Null
if (-not (Test-Path assets\icon.png)) { Invoke-Checked $VenvPy scripts\make_icon.py assets\icon.png }
Invoke-Checked $VenvPy scripts\make_ico.py assets\icon.png build\icon.ico

if (-not $NoModel) { Invoke-Checked $VenvPy scripts\download_model.py }

Write-Host "Збирання $AppName $Version…"
$env:BUNDLE_MODEL = if ($NoModel) { "0" } else { "1" }
$env:APP_ICON = Join-Path $Root "build\icon.ico"
Invoke-Checked $VenvPy -m PyInstaller --noconfirm --clean --log-level WARN `
    --distpath dist --workpath build\pyinstaller packaging\audiobook_reader.spec

if ($NoInstaller) {
    Write-Host "`nГотово: $Root\dist\$AppName\$AppName.exe"
    exit 0
}

$Iscc = (Get-Command iscc -ErrorAction SilentlyContinue).Source
if (-not $Iscc) {
    $Iscc = @("${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe", "$env:ProgramFiles\Inno Setup 6\ISCC.exe",
              "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe") | Where-Object { Test-Path $_ } | Select-Object -First 1
}
if (-not $Iscc) {
    throw "Inno Setup 6 не знайдено. Встановіть: winget install JRSoftware.InnoSetup (або запустіть з -NoInstaller)."
}
Invoke-Checked $Iscc /Q "/DAppVersion=$Version" "/DSourceDir=$Root\dist\$AppName" "/DOutputDir=$Root\dist" `
    "/DIconFile=$Root\build\icon.ico" packaging\windows\installer.iss

Write-Host "`nГотово:"
Write-Host "  $Root\dist\$AppName\$AppName.exe"
Write-Host "  $Root\dist\Local-Audiobook-Reader-$Version-Windows-Setup.exe  <- інсталятор"
