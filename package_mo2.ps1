[CmdletBinding()]
param(
    [string]$BuildDirectory = '',
    [string]$OutputDirectory = ''
)
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
if ([string]::IsNullOrWhiteSpace($BuildDirectory)) { $BuildDirectory = Join-Path $PSScriptRoot 'compiled' }
if ([string]::IsNullOrWhiteSpace($OutputDirectory)) { $OutputDirectory = Join-Path $PSScriptRoot '..\..\outputs' }

# Shared lookups: the ZIP names and every meta.ini version come from the one
# FrameworkInfo.Version literal, so an install can never mix two versions.
$environmentScript = Join-Path $PSScriptRoot 'Environment.ps1'
if (-not (Test-Path -LiteralPath $environmentScript -PathType Leaf)) { throw "找不到共享脚本：$environmentScript" }
. $environmentScript
$version = Get-SoD2SEVersion -SourceRoot $PSScriptRoot
$build = (Resolve-Path -LiteralPath $BuildDirectory).Path
$output = [IO.Path]::GetFullPath($OutputDirectory)
$staging = Join-Path $output ('MCM-MO2-staging-' + [Guid]::NewGuid().ToString('N'))

function Write-Mo2Meta([string]$path, [string]$id, [string]$name, [string]$notes, [string]$installationFile) {
    $content = @(
        '[General]',
        'gameName=State of Decay 2',
        'modID=0',
        ('version={0}' -f $version),
        ('newestVersion={0}' -f $version),
        'category=SoD2SE',
        ('installationFile={0}' -f $installationFile),
        ('notes={0}' -f $notes),
        ('name={0}' -f $name),
        ('soD2seId={0}' -f $id)
    )
    [IO.File]::WriteAllLines((Join-Path $path 'meta.ini'), $content, [Text.UTF8Encoding]::new($false))
}

try {
    [IO.Directory]::CreateDirectory($staging) | Out-Null
    foreach ($name in 'Mcm','MeleeSpeed','Roguelite','UnlimitedFollowers','UnlimitedCommunity') {
        $package = Join-Path $staging $name
        $plugins = Join-Path $package 'Root\Plugins'
        [IO.Directory]::CreateDirectory($plugins) | Out-Null
        Copy-Item -LiteralPath (Join-Path $build "Plugins\$name.dll") -Destination $plugins
        if ($name -eq 'Mcm') {
            Copy-Item -LiteralPath (Join-Path $build 'Plugins\Mcm') -Destination $plugins -Recurse
        }
        if ($name -eq 'MeleeSpeed') {
            Copy-Item -LiteralPath (Join-Path $build 'Plugins\MeleeSpeed') -Destination $plugins -Recurse
        }
        $zip = Join-Path $output "SoD2SE-$name-MO2-v$version.zip"
        $displayName = switch ($name) {
            'Mcm' { '模组配置菜单 - Mod Configuration Menu' }
            'MeleeSpeed' { '近战攻速 - Melee Attack Speed' }
            'Roguelite' { '幸存者成长 - Survivor Roguelite' }
            'UnlimitedFollowers' { '无限随从 - Unlimited Followers' }
            'UnlimitedCommunity' { '社区招募无上限 - Unlimited Community Recruitment' }
        }
        Write-Mo2Meta $package $name $displayName ("SoD2SE Mod release {0}; requires the SoD2SE framework {0}." -f $version) (Split-Path -Leaf $zip)
        Compress-Archive -Path (Join-Path $package '*') -DestinationPath $zip -Force
        Write-Output $zip
    }
    $framework = Join-Path $staging 'Framework'
    [IO.Directory]::CreateDirectory($framework) | Out-Null
    Copy-Item -LiteralPath (Join-Path $build 'SoD2SE.Loader.exe'), (Join-Path $build 'SoD2SE.Core.dll'), (Join-Path $build 'SoD2SE.GameApi.dll') -Destination $framework
    $frameworkZip = Join-Path $output "SoD2SE-Framework-MO2-v$version.zip"
    Compress-Archive -Path (Join-Path $framework '*') -DestinationPath $frameworkZip -Force
    Write-Output $frameworkZip
}
finally {
    if (Test-Path -LiteralPath $staging) {
        $resolvedStaging = [IO.Path]::GetFullPath($staging).TrimEnd('\')
        $outputBoundary = [IO.Path]::GetFullPath($output).TrimEnd('\') + '\'
        if (-not $resolvedStaging.StartsWith($outputBoundary, [StringComparison]::OrdinalIgnoreCase)) {
            throw "Refusing to clean staging outside output directory: $resolvedStaging"
        }
        Remove-Item -LiteralPath $resolvedStaging -Recurse -Force
        Write-Output "Staging cleaned: $resolvedStaging"
    }
}
