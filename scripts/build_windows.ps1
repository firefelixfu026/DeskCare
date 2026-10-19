param(
    [string]$Python = ".\.venv\Scripts\python.exe",
    [string]$OutputName = "DeskCare",
    [switch]$OneFile,
    [switch]$Verify,
    [int]$StartupSeconds = 20
)

$ErrorActionPreference = "Stop"
if (-not (Test-Path -LiteralPath $Python)) {
    throw "Python executable not found: $Python"
}
$pythonPath = (Resolve-Path -LiteralPath $Python).Path
$pythonScripts = Split-Path -Parent $pythonPath
$pythonBase = Split-Path -Parent $pythonScripts
# PyInstaller's Qt hooks may inspect PATH and accidentally collect Python/Qt
# DLLs from another installation. Keep the build ABI deterministic when the
# host has multiple Python versions (for example 3.12 and 3.14).
$env:PATH = @(
    $pythonScripts,
    $pythonBase,
    (Join-Path $env:SystemRoot "System32"),
    $env:SystemRoot
) -join [IO.Path]::PathSeparator
$assetPath = (Resolve-Path -LiteralPath ".\assets").Path
$entryPath = (Resolve-Path -LiteralPath ".\deskcare_launcher.py").Path
$layout = if ($OneFile) { "--onefile" } else { "--onedir" }
$workPath = if ($OneFile) { ".\build\DeskCare-onefile" } else { ".\build\DeskCare-onedir" }

& $Python -m PyInstaller --version
if ($LASTEXITCODE -ne 0) {
    throw "PyInstaller is not installed. Install the optional Windows build dependency first."
}

$args = @(
    "-m", "PyInstaller",
    "--noconfirm", "--clean", $layout, "--windowed",
    "--name", $OutputName,
    "--workpath", $workPath,
    "--add-data", "$assetPath;assets",
    "--specpath", "build",
    "--exclude-module", "vosk",
    "--exclude-module", "PySide6.QtMultimedia",
    "--exclude-module", "PySide6.QtMultimediaWidgets",
    $entryPath
)
& $Python @args
if ($LASTEXITCODE -ne 0) {
    throw "PyInstaller build failed with exit code $LASTEXITCODE"
}
if ($OneFile) {
    Write-Host "Built dist\$OutputName.exe (onefile)"
    $builtExecutable = ".\dist\$OutputName.exe"
} else {
    Write-Host "Built dist\$OutputName\$OutputName.exe (onedir; copy the whole folder)"
    $builtExecutable = ".\dist\$OutputName\$OutputName.exe"
}
if ($Verify) {
    $verificationScript = (Resolve-Path -LiteralPath ".\scripts\verify_windows_package.ps1").Path
    $verificationRoot = Join-Path (Resolve-Path -LiteralPath ".\build").Path "package-smoke"
    & $verificationScript -Executable $builtExecutable -StartupSeconds $StartupSeconds -TemporaryRoot $verificationRoot
}
