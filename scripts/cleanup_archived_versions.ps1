param(
    [string]$ProjectRoot = (Split-Path -Parent $PSScriptRoot),
    [Parameter(Mandatory=$true)][string]$CurrentExeSha256
)
$ErrorActionPreference = 'Stop'
function Get-ArchiveHash([string]$LiteralPath) {
    $stream = [IO.File]::OpenRead($LiteralPath)
    $algorithm = [Security.Cryptography.SHA256]::Create()
    try { return [BitConverter]::ToString($algorithm.ComputeHash($stream)).Replace('-','').ToLowerInvariant() }
    finally { $algorithm.Dispose(); $stream.Dispose() }
}
$project = (Resolve-Path -LiteralPath $ProjectRoot).Path
$archiveRoot = Join-Path $project 'release/Legacy-Archive-2026-10-21'
$indexPath = Join-Path $archiveRoot 'Legacy-Archive-Index.json'
$receiptPath = Join-Path $archiveRoot 'UPLOAD-VERIFIED.json'
$currentExe = Join-Path $project 'dist/DeskCare-UI14/DeskCare-UI14.exe'
if (-not (Test-Path -LiteralPath $currentExe -PathType Leaf)) { throw 'Replacement UI14 build missing; cleanup denied' }
if ((Get-ArchiveHash $currentExe) -ne $CurrentExeSha256) { throw 'Replacement build hash mismatch' }
$index = Get-Content -LiteralPath $indexPath -Raw -Encoding UTF8 | ConvertFrom-Json
$receipt = Get-Content -LiteralPath $receiptPath -Raw -Encoding UTF8 | ConvertFrom-Json
if ($receipt.index_sha256 -ne (Get-ArchiveHash $indexPath)) { throw 'Index mismatch; cleanup denied' }
if ($receipt.release -ne 'https://github.com/firefelixfu026/DeskCare/releases/tag/legacy-archive-2026-10-21') { throw 'Unexpected remote archive' }
foreach ($part in $index.parts) {
    if ($part.name -notmatch '^DeskCare-Legacy-Archive-part\d\d.zip$') { throw 'Unsafe archive part name' }
    $remote = @($receipt.assets | Where-Object name -eq $part.name)
    if ($remote.Count -ne 1 -or $remote[0].sha256 -ne $part.sha256 -or $remote[0].size -ne $part.size) { throw 'Missing server verification; cleanup denied' }
    $partPath = Join-Path $archiveRoot $part.name
    if (Test-Path -LiteralPath $partPath) {
        if ((Get-ArchiveHash $partPath) -ne $part.sha256) { throw 'Local archive mismatch' }
    }
}
$removedBytes = [long]0
$removedFiles = 0
$kept = @()
foreach ($relative in $index.manifest.targets) {
    $target = [IO.Path]::GetFullPath((Join-Path $project $relative))
    $parent = Split-Path -Parent $target
    $allowedParent = @((Join-Path $project 'dist'),(Join-Path $project 'release'))
    if ($parent -notin $allowedParent -or $relative -match 'UI14|\.\.') { throw 'Unsafe cleanup target' }
    if (-not (Test-Path -LiteralPath $target)) { continue }
    if ((Get-Item -LiteralPath $target -Force).Attributes -band [IO.FileAttributes]::ReparsePoint) { throw 'Linked cleanup target' }
    if (git -C $project ls-files -- $relative) { throw 'Tracked source file in cleanup target' }
    $expected = @($index.manifest.files | Where-Object { $_.path -eq $relative -or $_.path.StartsWith($relative + '/') })
    $directories = @()
    $actual = if (Test-Path -LiteralPath $target -PathType Leaf) { @(Get-Item -LiteralPath $target) } else {
        $pending = [Collections.Generic.Stack[string]]::new()
        $pending.Push($target)
        @(while ($pending.Count) {
            $folder = $pending.Pop()
            foreach ($entry in Get-ChildItem -LiteralPath $folder -Force) {
                if ($entry.Attributes -band [IO.FileAttributes]::ReparsePoint) { throw 'Linked path in cleanup target' }
                if ($entry.PSIsContainer) { $directories += $entry; $pending.Push($entry.FullName) } else { $entry }
            }
        })
    }
    if ($actual.Count -ne $expected.Count) { $kept += $relative; continue }
    $valid = $true
    foreach ($file in $expected) {
        $path = [IO.Path]::GetFullPath((Join-Path $project $file.path))
        if ($path -ne $target -and -not $path.StartsWith($target + [IO.Path]::DirectorySeparatorChar,[StringComparison]::OrdinalIgnoreCase)) { throw 'File escaped validated target' }
        $item = Get-Item -LiteralPath $path -Force -ErrorAction SilentlyContinue
        if ($null -eq $item -or $item.Attributes -band [IO.FileAttributes]::ReparsePoint -or $item.Length -ne $file.size -or (Get-ArchiveHash $path) -ne $file.sha256) { $valid=$false; break }
        # Read-only probes do not detect Windows image-section locks. Request
        # write access without writing so a running EXE/DLL keeps its whole
        # directory intact rather than leaving a partial runtime behind.
        try { $probe = [IO.File]::Open($path,[IO.FileMode]::Open,[IO.FileAccess]::ReadWrite,[IO.FileShare]::None); $probe.Dispose() }
        catch { $valid=$false; break }
    }
    if (-not $valid) { $kept += $relative; continue }
    foreach ($file in $expected) {
        $path = [IO.Path]::GetFullPath((Join-Path $project $file.path))
        try {
            Remove-Item -LiteralPath $path -Force -ErrorAction Stop
            $removedBytes += [long]$file.size
            $removedFiles++
        } catch { $kept += $file.path }
    }
    if (Test-Path -LiteralPath $target -PathType Container) {
        $directories | Sort-Object { $_.FullName.Length } -Descending | ForEach-Object {
            if (-not (Get-ChildItem -LiteralPath $_.FullName -Force | Select-Object -First 1)) { Remove-Item -LiteralPath $_.FullName -Force }
        }
        if (-not (Get-ChildItem -LiteralPath $target -Force | Select-Object -First 1)) { Remove-Item -LiteralPath $target -Force }
    }
}
# Archives themselves are recoverable from the verified GitHub release.
foreach ($part in $index.parts) {
    $partPath = Join-Path $archiveRoot $part.name
    if (Test-Path -LiteralPath $partPath) { Remove-Item -LiteralPath $partPath -Force }
}
$result = [pscustomobject]@{removedFiles=$removedFiles;releasedBytes=$removedBytes;kept=$kept;recovery=$receipt.release}
$result | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath (Join-Path $archiveRoot 'CLEANUP-RESULT.json') -Encoding UTF8
$result | ConvertTo-Json -Depth 5
