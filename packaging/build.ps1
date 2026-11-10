# Build dist\FocusBlocks\FocusBlocks.exe with PyInstaller, then dist\FocusBlocks-Setup-<version>.exe with Inno Setup.
#
#   powershell -ExecutionPolicy Bypass -File packaging\build.ps1            # exe + installer
#   powershell -ExecutionPolicy Bypass -File packaging\build.ps1 -ExeOnly   # skip the installer
#
# Needs Inno Setup 6 for the installer step (winget install JRSoftware.InnoSetup).

param([switch]$ExeOnly)

$ErrorActionPreference = "Stop"
$root = Split-Path $PSScriptRoot -Parent
Set-Location $root

$py = Join-Path $root ".venv\Scripts\python.exe"
if (-not (Test-Path $py)) { $py = "python" }

Write-Host "Installing build tools..."
# Only PyInstaller: reinstalling focusblocks itself fails while a copy is running from this venv.
# The app's own dependencies must already be installed (pip install -e .).
& $py -m pip install --quiet "pyinstaller>=6.10"
if ($LASTEXITCODE) { throw "pip install failed" }

$version = (& $py -c "import sys; sys.path.insert(0, 'src'); import focusblocks; print(focusblocks.__version__)").Trim()
Write-Host "Building Focus Blocks $version"

$distExe = Join-Path $root "dist\FocusBlocks\FocusBlocks.exe"
$running = Get-Process FocusBlocks -ErrorAction SilentlyContinue | Where-Object { $_.Path -eq $distExe }
if ($running) {
    throw "FocusBlocks.exe is running from dist\FocusBlocks, which locks its files. Quit it (right-click the pill > Quit) and run this again."
}

& $py packaging\make_icon.py build\focusblocks.ico
if ($LASTEXITCODE) { throw "icon failed" }

& $py -m PyInstaller --noconfirm --clean --windowed `
    --name FocusBlocks `
    --icon "$root\build\focusblocks.ico" `
    --paths "$root\src" `
    --collect-submodules focusblocks `
    --collect-submodules pyvda `
    --exclude-module numpy --exclude-module yaml `
    --distpath dist --workpath build\pyinstaller --specpath build `
    "$root\packaging\launcher.py"
if ($LASTEXITCODE) { throw "PyInstaller failed" }
Write-Host "Built dist\FocusBlocks\FocusBlocks.exe"

if ($ExeOnly) { return }

$iscc = @(
    (Get-Command iscc.exe -ErrorAction SilentlyContinue).Source,
    "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
    "$env:ProgramFiles\Inno Setup 6\ISCC.exe",
    "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe"
) | Where-Object { $_ -and (Test-Path $_) } | Select-Object -First 1
if (-not $iscc) {
    throw "Inno Setup 6 not found. Install it (winget install JRSoftware.InnoSetup) and run this again."
}

& $iscc "/DAppVersion=$version" packaging\installer.iss
if ($LASTEXITCODE) { throw "Inno Setup failed" }
Write-Host "Built dist\FocusBlocks-Setup-$version.exe"
