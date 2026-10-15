param(
    [Parameter(Mandatory = $true)]
    [string]$Executable,
    [int]$StartupSeconds = 20,
    [string]$TemporaryRoot = ([IO.Path]::GetTempPath())
)

$ErrorActionPreference = "Stop"
if ($StartupSeconds -lt 1 -or $StartupSeconds -gt 30) {
    throw "StartupSeconds must be between 1 and 30."
}
if (-not (Test-Path -LiteralPath $Executable -PathType Leaf)) {
    throw "DeskCare executable not found: $Executable"
}

$executablePath = (Resolve-Path -LiteralPath $Executable).Path
if ([IO.Path]::GetExtension($executablePath) -ne ".exe") {
    throw "Expected a Windows .exe package: $executablePath"
}

$processName = [IO.Path]::GetFileNameWithoutExtension($executablePath)
$packageDirectory = Split-Path -Parent $executablePath
$internalDirectory = Join-Path $packageDirectory "_internal"
if (Test-Path -LiteralPath $internalDirectory -PathType Container) {
    $qtCore = Join-Path $internalDirectory "PySide6\Qt6Core.dll"
    if (-not (Test-Path -LiteralPath $qtCore -PathType Leaf)) {
        throw "Incomplete onedir package: missing $qtCore"
    }
}

$existing = Get-Process -Name $processName -ErrorAction SilentlyContinue |
    Where-Object {
        try { $_.Path -eq $executablePath } catch { $false }
    }
if ($existing) {
    throw "A process from this package is already running. Exit it before verification."
}

New-Item -ItemType Directory -Force -Path $TemporaryRoot | Out-Null
$smokeData = Join-Path $TemporaryRoot ("DeskCare-package-smoke-" + [Guid]::NewGuid().ToString("N"))
New-Item -ItemType Directory -Path $smokeData | Out-Null

$previousLocalAppData = $env:LOCALAPPDATA
$startedAt = Get-Date
$startedProcesses = @()
try {
    # Keep the smoke run separate from the user's real DeskCare database.
    $env:LOCALAPPDATA = $smokeData
    Start-Process -FilePath $executablePath -ArgumentList "--demo" | Out-Null
    Start-Sleep -Seconds $StartupSeconds

    $startedProcesses = @(Get-Process -Name $processName -ErrorAction SilentlyContinue |
        Where-Object {
            try {
                $_.Path -eq $executablePath -and $_.StartTime -ge $startedAt.AddSeconds(-2)
            } catch {
                $false
            }
        })
    if (-not $startedProcesses) {
        throw "DeskCare exited before the startup check completed."
    }

    $exceptionWindows = @($startedProcesses |
        Where-Object { $_.MainWindowTitle -match "Unhandled exception" })
    if ($exceptionWindows) {
        throw "DeskCare opened an unhandled-exception window."
    }

    $mainWindows = @($startedProcesses |
        Where-Object { $_.MainWindowTitle -eq "DeskCare" })
    if (-not $mainWindows) {
        throw "DeskCare process started, but the main window was not ready."
    }

    Write-Host "Package verification passed: $executablePath"
} finally {
    $startedProcesses = @(Get-Process -Name $processName -ErrorAction SilentlyContinue |
        Where-Object {
            try {
                $_.Path -eq $executablePath -and $_.StartTime -ge $startedAt.AddSeconds(-2)
            } catch {
                $false
            }
        })
    foreach ($process in $startedProcesses) {
        Stop-Process -Id $process.Id -Force -ErrorAction SilentlyContinue
    }
    if ($null -eq $previousLocalAppData) {
        Remove-Item Env:LOCALAPPDATA -ErrorAction SilentlyContinue
    } else {
        $env:LOCALAPPDATA = $previousLocalAppData
    }
    Start-Sleep -Milliseconds 500
    if (Test-Path -LiteralPath $smokeData) {
        Remove-Item -LiteralPath $smokeData -Recurse -Force
    }
}
