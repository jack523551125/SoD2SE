[CmdletBinding()]
param(
    [string]$PackageDirectory = '',
    [string]$ZipPath = '',
    [switch]$CleanPackageDirectory
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

if (Test-Path -LiteralPath (Join-Path $PSScriptRoot 'Core\SoD2SE.Core.cs')) {
    $sourceRoot = $PSScriptRoot
} else {
    $sourceRoot = Join-Path $PSScriptRoot 'source'
}

# Shared lookups: FrameworkInfo.Version is the only version literal, so the
# package name, the release manifest and every MO2 meta.ini agree by
# construction.
$environmentScript = Join-Path $PSScriptRoot 'Environment.ps1'
if (-not (Test-Path -LiteralPath $environmentScript -PathType Leaf)) { throw "找不到共享脚本：$environmentScript" }
. $environmentScript
$version = Get-SoD2SEVersion -SourceRoot $sourceRoot

if ([string]::IsNullOrWhiteSpace($PackageDirectory)) {
    $PackageDirectory = Join-Path $PSScriptRoot "..\..\outputs\SoD2SE-CommunityMods-v$version"
}
if ([string]::IsNullOrWhiteSpace($ZipPath)) {
    $ZipPath = Join-Path $PSScriptRoot "..\..\outputs\SoD2SE-CommunityMods-v$version.zip"
}
$metadataRoot = $PSScriptRoot
$buildScript = Join-Path $sourceRoot 'build.ps1'
if (-not (Test-Path -LiteralPath $buildScript -PathType Leaf)) { throw "找不到构建脚本：$buildScript" }

$packagePath = $ExecutionContext.SessionState.Path.GetUnresolvedProviderPathFromPSPath($PackageDirectory)
$zipPath = $ExecutionContext.SessionState.Path.GetUnresolvedProviderPathFromPSPath($ZipPath)
$staging = Join-Path ([IO.Path]::GetTempPath()) ('SoD2SE-package-' + [Guid]::NewGuid().ToString('N'))
$compiled = Join-Path $staging 'compiled'

# Only recursively remove generated directories, after checking their resolved
# absolute location against the intended parent. Never clean an arbitrary tree.
function Remove-GeneratedDirectory([string]$Path, [string]$Parent) {
    $resolved = [IO.Path]::GetFullPath($Path).TrimEnd('\')
    $boundary = [IO.Path]::GetFullPath($Parent).TrimEnd('\') + '\'
    if (-not $resolved.StartsWith($boundary, [StringComparison]::OrdinalIgnoreCase)) {
        throw "拒绝清理目标目录之外的路径：$resolved"
    }
    if (Test-Path -LiteralPath $resolved) { Remove-Item -LiteralPath $resolved -Recurse -Force }
}

try {
    [IO.Directory]::CreateDirectory($staging) | Out-Null
    & $buildScript -OutputDirectory $compiled
    if ($LASTEXITCODE -ne 0) { throw "构建失败：$LASTEXITCODE" }

    Copy-Item -LiteralPath (Join-Path $compiled 'SoD2SE.Loader.exe'), (Join-Path $compiled 'SoD2SE.Core.dll'), (Join-Path $compiled 'SoD2SE.GameApi.dll') -Destination $staging -Force
    [IO.Directory]::CreateDirectory((Join-Path $staging 'Plugins')) | Out-Null
    Get-ChildItem -LiteralPath (Join-Path $compiled 'Plugins') | Copy-Item -Destination (Join-Path $staging 'Plugins') -Recurse -Force
    Get-ChildItem -LiteralPath $metadataRoot -File | Where-Object { $_.Name -like '*patch-manifest.json' -or $_.Name -in @('README.zh-CN.md','VERIFICATION.zh-CN.md','COMMUNITY.zh-CN.md','MCM.zh-CN.md','MELEE.zh-CN.md','UI.zh-CN.md') -or $_.Name -like 'verify_*.py' } | Copy-Item -Destination $staging -Force
    Copy-Item -LiteralPath (Join-Path $metadataRoot 'Research') -Destination $staging -Recurse -Force
    Copy-Item -LiteralPath (Join-Path $sourceRoot 'verify_all.ps1'), (Join-Path $sourceRoot 'Environment.ps1'), (Join-Path $PSScriptRoot 'package.ps1'), (Join-Path $PSScriptRoot 'package_mo2.ps1') -Destination $staging -Force

    $sourceDestination = Join-Path $staging 'source'
    [IO.Directory]::CreateDirectory((Join-Path $sourceDestination 'Core')) | Out-Null
    [IO.Directory]::CreateDirectory((Join-Path $sourceDestination 'GameApi')) | Out-Null
    [IO.Directory]::CreateDirectory((Join-Path $sourceDestination 'Loader')) | Out-Null
    Copy-Item -LiteralPath (Join-Path $sourceRoot 'Plugins') -Destination $sourceDestination -Recurse -Force
    $nativeRoot = Join-Path $sourceRoot 'Native'
    $nativeDestination = Join-Path $sourceDestination 'Native'
    [IO.Directory]::CreateDirectory($nativeDestination) | Out-Null
    Get-ChildItem -LiteralPath $nativeRoot -File |
    Where-Object { $_.Extension -notin '.lib', '.exp', '.obj', '.pdb', '.ilk', '.log' } |
    Copy-Item -Destination $nativeDestination -Force
    $imguiDestination = Join-Path $nativeDestination 'vendor\imgui'
    [IO.Directory]::CreateDirectory((Join-Path $imguiDestination 'backends')) | Out-Null
    Get-ChildItem -LiteralPath (Join-Path $nativeRoot 'vendor\imgui') -File | Where-Object { $_.Extension -in '.cpp','.h','.txt' } | Copy-Item -Destination $imguiDestination
    foreach ($file in 'imgui_impl_dx11.cpp','imgui_impl_dx11.h','imgui_impl_win32.cpp','imgui_impl_win32.h') {
        Copy-Item -LiteralPath (Join-Path $nativeRoot "vendor\imgui\backends\$file") -Destination (Join-Path $imguiDestination 'backends')
    }
    $minhookDestination = Join-Path $nativeDestination 'vendor\minhook'
    [IO.Directory]::CreateDirectory($minhookDestination) | Out-Null
    foreach ($name in 'CMakeLists.txt','LICENSE.txt','cmake','include','src') {
        Copy-Item -LiteralPath (Join-Path $nativeRoot "vendor\minhook\$name") -Destination $minhookDestination -Recurse
    }
    if (Test-Path -LiteralPath (Join-Path $sourceRoot 'Tests')) {
        Copy-Item -LiteralPath (Join-Path $sourceRoot 'Tests') -Destination $sourceDestination -Recurse -Force
    }
    Copy-Item -LiteralPath (Join-Path $sourceRoot 'build.ps1'), (Join-Path $sourceRoot 'Environment.ps1') -Destination $sourceDestination -Force
    Get-ChildItem -LiteralPath (Join-Path $sourceRoot 'Core') -Filter '*.cs' -File | Copy-Item -Destination (Join-Path $sourceDestination 'Core') -Force
    Get-ChildItem -LiteralPath (Join-Path $sourceRoot 'GameApi') -Filter '*.cs' -File | Copy-Item -Destination (Join-Path $sourceDestination 'GameApi') -Force
    Get-ChildItem -LiteralPath (Join-Path $sourceRoot 'Loader') -Filter '*.cs' -File | Copy-Item -Destination (Join-Path $sourceDestination 'Loader') -Force
    Get-ChildItem -LiteralPath $staging -Directory -Recurse -Force |
        Where-Object { $_.Name -eq '__pycache__' } |
        Sort-Object FullName -Descending |
        ForEach-Object { Remove-GeneratedDirectory $_.FullName $staging }
    Remove-GeneratedDirectory $compiled $staging

    $manifest = Get-Content -LiteralPath (Join-Path $staging 'patch-manifest.json') -Raw | ConvertFrom-Json
    $files = @(
        Get-ChildItem -LiteralPath $staging -Recurse -File |
            Where-Object { $_.Name -ne 'RELEASE-MANIFEST.json' } |
            Sort-Object FullName |
            ForEach-Object {
                [ordered]@{
                    path = $_.FullName.Substring($staging.Length + 1).Replace('\', '/')
                    size = $_.Length
                    sha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath $_.FullName).Hash
                }
            }
    )
    [ordered]@{
        package = ('SoD2SE-CommunityMods-v' + $version)
        framework = $version
        plugins = @(Get-ChildItem -LiteralPath (Join-Path $staging 'Plugins') -Filter '*.dll' -File | Sort-Object Name | Select-Object -ExpandProperty Name)
        steam_app_id = $manifest.steam_app_id
        steam_build_id = $manifest.steam_build_id
        target_sha256 = $manifest.sha256
        files = $files
    } | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath (Join-Path $staging 'RELEASE-MANIFEST.json') -Encoding UTF8

    $zipParent = Split-Path -Parent $zipPath
    [IO.Directory]::CreateDirectory($zipParent) | Out-Null
    Compress-Archive -Path (Join-Path $staging '*') -DestinationPath $zipPath -CompressionLevel Optimal -Force

    if ($CleanPackageDirectory -and (Test-Path -LiteralPath $packagePath)) {
        $outputRoot = [IO.Path]::GetFullPath((Split-Path -Parent $packagePath))
        if (-not (Test-Path -LiteralPath (Join-Path $packagePath 'RELEASE-MANIFEST.json') -PathType Leaf)) {
            throw "拒绝清理没有发布清单的目录：$packagePath"
        }
        Remove-GeneratedDirectory $packagePath $outputRoot
    }
    [IO.Directory]::CreateDirectory($packagePath) | Out-Null
    Copy-Item -Path (Join-Path $staging '*') -Destination $packagePath -Recurse -Force
    Write-Output "Package：$packagePath"
    Write-Output "ZIP：$zipPath"
} finally {
    Remove-GeneratedDirectory $staging ([IO.Path]::GetTempPath())
}
