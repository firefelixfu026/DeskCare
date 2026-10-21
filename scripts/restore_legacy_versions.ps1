param([Parameter(Mandatory=$true)][string]$Destination)
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.IO.Compression.FileSystem
function Get-ArchiveHash([string]$LiteralPath) {
    $stream = [IO.File]::OpenRead($LiteralPath)
    $algorithm = [Security.Cryptography.SHA256]::Create()
    try { return [BitConverter]::ToString($algorithm.ComputeHash($stream)).Replace('-','').ToLowerInvariant() }
    finally { $algorithm.Dispose(); $stream.Dispose() }
}
$restoreRoot = [IO.Path]::GetFullPath($Destination)
if (Test-Path -LiteralPath $restoreRoot) { throw 'Choose a new destination folder. Existing files are never overwritten.' }
$firstPart = Join-Path $PSScriptRoot 'DeskCare-Legacy-Archive-part01.zip'
$part = [IO.Compression.ZipFile]::OpenRead($firstPart)
try {
    $reader = [IO.StreamReader]::new($part.GetEntry('MANIFEST.json').Open(), [Text.Encoding]::UTF8)
    try { $manifest = $reader.ReadToEnd() | ConvertFrom-Json } finally { $reader.Dispose() }
} finally { $part.Dispose() }
if ($manifest.format -ne 1) { throw 'Unsupported archive format' }
$null = New-Item -ItemType Directory -Path $restoreRoot
$prefix = $restoreRoot.TrimEnd([IO.Path]::DirectorySeparatorChar,[IO.Path]::AltDirectorySeparatorChar) + [IO.Path]::DirectorySeparatorChar
foreach ($file in $manifest.files) {
    $target = [IO.Path]::GetFullPath((Join-Path $restoreRoot $file.path))
    if (-not $target.StartsWith($prefix, [StringComparison]::OrdinalIgnoreCase)) { throw 'Unsafe restore target' }
    if ($file.sha256 -notmatch '^[0-9a-f]{64}$') { throw 'Invalid object hash' }
    $object = $manifest.objects.PSObject.Properties[$file.sha256].Value
    if ($object.part -notmatch '^DeskCare-Legacy-Archive-part\d\d.zip$') { throw 'Invalid part name' }
    $parent = Split-Path -Parent $target
    $null = New-Item -ItemType Directory -Force -Path $parent
    $part = [IO.Compression.ZipFile]::OpenRead((Join-Path $PSScriptRoot $object.part))
    try {
        $entry = $part.GetEntry(('objects/' + $file.sha256))
        if ($null -eq $entry) { throw 'Missing object. Download all archive parts.' }
        [IO.Compression.ZipFileExtensions]::ExtractToFile($entry, $target, $false)
    } finally { $part.Dispose() }
    if ((Get-ArchiveHash $target) -ne $file.sha256) { throw 'Restore hash mismatch' }
}
Write-Output ('Restored ' + $manifest.files.Count + ' verified files to ' + $restoreRoot)
