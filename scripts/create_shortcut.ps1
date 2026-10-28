# Create a desktop shortcut that starts Local Audiobook Reader from this project folder (Windows):
#
#   powershell -ExecutionPolicy Bypass -File scripts\create_shortcut.ps1
#
# Needs the environment from scripts/setup.sh. Run again after moving the project folder.
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$Pythonw = Join-Path $Root ".venv\Scripts\pythonw.exe"
if (-not (Test-Path $Pythonw)) { throw "Середовище не встановлено. Спершу виконайте: scripts/setup.sh" }

# The .ico is generated next to the user data (data\ is not tracked by git).
$Icon = Join-Path $Root "data\icon.ico"
New-Item -ItemType Directory -Force -Path (Split-Path $Icon) | Out-Null
& (Join-Path $Root ".venv\Scripts\python.exe") (Join-Path $Root "scripts\make_ico.py") (Join-Path $Root "assets\icon.png") $Icon
if ($LASTEXITCODE -ne 0) { throw "Не вдалося створити значок" }

$Desktop = [Environment]::GetFolderPath("Desktop")  # also right when the desktop is in OneDrive
$Link = Join-Path $Desktop "Local Audiobook Reader.lnk"
$Shell = New-Object -ComObject WScript.Shell
$Shortcut = $Shell.CreateShortcut($Link)
$Shortcut.TargetPath = $Pythonw
$Shortcut.Arguments = "`"$(Join-Path $Root 'run.pyw')`""
$Shortcut.WorkingDirectory = $Root
$Shortcut.IconLocation = "$Icon,0"
$Shortcut.Description = "Local Audiobook Reader"
$Shortcut.Save()
Write-Host "Ярлик створено: $Link"
