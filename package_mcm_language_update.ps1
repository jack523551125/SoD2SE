[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$BuildDirectory,
    [Parameter(Mandatory = $true)][string]$McmSettingsAsset,
    [string]$OutputDirectory = ''
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

if ([string]::IsNullOrWhiteSpace($OutputDirectory)) {
    $OutputDirectory = Join-Path $PSScriptRoot '..\..\outputs'
}
$build = [IO.Path]::GetFullPath((Resolve-Path -LiteralPath $BuildDirectory).ProviderPath)
if (-not (Test-Path -LiteralPath $McmSettingsAsset -PathType Leaf)) { throw "Combined native Settings asset not found: $McmSettingsAsset" }
$mcmAsset = [IO.Path]::GetFullPath((Resolve-Path -LiteralPath $McmSettingsAsset).ProviderPath)
$output = [IO.Path]::GetFullPath($OutputDirectory)
$mcmVersion = '0.6.3-preview'
$entryVersion = '0.2.9-preview'
$staging = Join-Path $output ('McmLanguageUpdate-staging-' + [Guid]::NewGuid().ToString('N'))

function Write-PackageMeta([string]$directory, [string]$version, [string]$name, [string]$id, [string]$archiveName, [string]$notes) {
    $contents = @(
        '[General]',
        'gameName=State of Decay 2',
        'modID=0',
        ('version={0}.0-preview' -f $version),
        ('newestVersion={0}.0-preview' -f $version),
        'category=SoD2SE',
        ('installationFile={0}' -f $archiveName),
        ('notes={0}' -f $notes),
        ('name={0}' -f $name),
        ('soD2seId={0}' -f $id)
    )
    [IO.File]::WriteAllLines((Join-Path $directory 'meta.ini'), $contents, [Text.UTF8Encoding]::new($false))
}

function Confirm-Mo2Package([string]$archive, [string]$version, [string]$name, [hashtable]$expectedFiles) {
    $verifyDir = Join-Path $staging ('verify-' + [Guid]::NewGuid().ToString('N'))
    try {
        Expand-Archive -LiteralPath $archive -DestinationPath $verifyDir
        if (-not (Test-Path -LiteralPath (Join-Path $verifyDir 'meta.ini') -PathType Leaf) -or
            -not ((Test-Path -LiteralPath (Join-Path $verifyDir 'Root') -PathType Container) -or (Test-Path -LiteralPath (Join-Path $verifyDir 'Saved') -PathType Container)) -or
            (Test-Path -LiteralPath (Join-Path $verifyDir 'Docs'))) {
            throw "MO2 archive layout validation failed: $archive"
        }
        $meta = Get-Content -LiteralPath (Join-Path $verifyDir 'meta.ini') -Raw
        $archiveName = [IO.Path]::GetFileName($archive)
        foreach ($line in @("version=$($version).0-preview", "newestVersion=$($version).0-preview", "installationFile=$archiveName", "name=$name")) {
            if (-not $meta.Contains($line)) { throw "MO2 metadata is missing '$line': $archive" }
        }
        $actual = [Collections.Generic.HashSet[string]]::new([StringComparer]::OrdinalIgnoreCase)
        foreach ($file in Get-ChildItem -LiteralPath $verifyDir -Recurse -File) {
            [void]$actual.Add($file.FullName.Substring($verifyDir.Length + 1).Replace('\', '/'))
        }
        if ($actual.Count -ne $expectedFiles.Count + 1 -or -not $actual.Contains('meta.ini')) {
            throw "Unexpected files in MO2 archive: $archive"
        }
        foreach ($relative in $expectedFiles.Keys) {
            if (-not $actual.Contains($relative)) { throw "MO2 archive is missing ${relative}: $archive" }
            $packaged = Get-FileHash -LiteralPath (Join-Path $verifyDir ($relative.Replace('/', '\'))) -Algorithm SHA256
            $source = Get-FileHash -LiteralPath $expectedFiles[$relative] -Algorithm SHA256
            if ($packaged.Hash -ne $source.Hash) { throw "MO2 archive payload hash mismatch for ${relative}: $archive" }
        }
    }
    finally {
        if (Test-Path -LiteralPath $verifyDir) { Remove-Item -LiteralPath $verifyDir -Recurse -Force }
    }
}

try {
    foreach ($file in @(
        (Join-Path $build 'Plugins\Mcm.dll'),
        (Join-Path $build 'Plugins\Mcm\SoD2SE.Mcm.Native.dll')
    )) {
        if (-not (Test-Path -LiteralPath $file -PathType Leaf)) { throw "MCM build is incomplete: $file" }
    }
    if (-not (Test-Path -LiteralPath (Join-Path $build 'SoD2SE.Core.dll') -PathType Leaf)) {
        throw 'Build is missing SoD2SE.Core.dll.'
    }

    [IO.Directory]::CreateDirectory($output) | Out-Null
    [IO.Directory]::CreateDirectory($staging) | Out-Null

    $mcmName = 'SoD2SE-Mcm-MO2-v0.6.3-preview-native-settings.zip'
    $mcmRoot = Join-Path $staging 'Mcm\Root\Plugins'
    [IO.Directory]::CreateDirectory((Join-Path $mcmRoot 'Mcm')) | Out-Null
    Copy-Item -LiteralPath (Join-Path $build 'Plugins\Mcm.dll') -Destination $mcmRoot
    Copy-Item -LiteralPath (Join-Path $build 'Plugins\Mcm\SoD2SE.Mcm.Native.dll') -Destination (Join-Path $mcmRoot 'Mcm')
    Write-PackageMeta (Join-Path $staging 'Mcm') '0.6.3' '模组配置菜单 - Mod Configuration Menu' 'Mcm' $mcmName '0.6.3-preview: detect game language automatically; no manual language setting.'
    $mcmZip = Join-Path $output $mcmName
    if (-not (Test-Path -LiteralPath $mcmZip)) { Compress-Archive -Path (Join-Path $staging 'Mcm\*') -DestinationPath $mcmZip }
    $mcmFiles = @{
        'Root/Plugins/Mcm.dll' = Join-Path $build 'Plugins\Mcm.dll'
        'Root/Plugins/Mcm/SoD2SE.Mcm.Native.dll' = Join-Path $build 'Plugins\Mcm\SoD2SE.Mcm.Native.dll'
    }
    Confirm-Mo2Package $mcmZip '0.6.3' '模组配置菜单 - Mod Configuration Menu' $mcmFiles

    $entryName = 'SoD2-NativeModSettingsEntry-MO2-v0.2.9-preview.zip'
    $entryDir = Join-Path $staging 'NativeEntry'
    $assetRelative = 'Saved\Cooked\WindowsNoEditor\StateOfDecay2\Content\Art\UI'
    $assetDir = Join-Path $entryDir $assetRelative
    [IO.Directory]::CreateDirectory($assetDir) | Out-Null
    Copy-Item -LiteralPath $mcmAsset -Destination (Join-Path $assetDir 'settings.uasset')
    Write-PackageMeta $entryDir '0.2.9' '原版 Mod 设置入口 - Native Mod Settings Entry' 'NativeModSettingsEntry' $entryName '0.2.9-preview: native-style dark numeric input fields.'
    $entryZip = Join-Path $output $entryName
    if (-not (Test-Path -LiteralPath $entryZip)) { Compress-Archive -Path (Join-Path $entryDir '*') -DestinationPath $entryZip }
    $entryFiles = @{
        'Saved/Cooked/WindowsNoEditor/StateOfDecay2/Content/Art/UI/settings.uasset' = $mcmAsset
    }
    Confirm-Mo2Package $entryZip '0.2.9' '原版 Mod 设置入口 - Native Mod Settings Entry' $entryFiles

    foreach ($archive in @($mcmZip, $entryZip)) {
        Write-Output ("PASS package: {0}; SHA-256={1}" -f $archive, (Get-FileHash -LiteralPath $archive -Algorithm SHA256).Hash.ToLowerInvariant())
    }
    Write-Output "MCM Core dependency: $((Join-Path $build 'SoD2SE.Core.dll'))"
}
finally {
    if (Test-Path -LiteralPath $staging) {
        $resolvedStaging = [IO.Path]::GetFullPath($staging).TrimEnd('\')
        $outputBoundary = [IO.Path]::GetFullPath($output).TrimEnd('\') + '\'
        if (-not $resolvedStaging.StartsWith($outputBoundary, [StringComparison]::OrdinalIgnoreCase)) {
            throw "Refusing to clean staging outside output directory: $resolvedStaging"
        }
        Remove-Item -LiteralPath $resolvedStaging -Recurse -Force
    }
}
