[CmdletBinding()]
param(
    [string]$BuildDirectory = '',
    [string]$OutputDirectory = (Join-Path (Split-Path -Parent (Split-Path -Parent $PSScriptRoot)) '..\..\dist'),
    [string]$NativeSettingsAsset = '',
    [string[]]$Ids = @(),
    [switch]$IncludeFramework,
    [switch]$RequireComplete,
    [switch]$ValidateOnly
)
$projectRoot = (Split-Path -Parent (Split-Path -Parent $PSScriptRoot))


Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
. (Join-Path $projectRoot 'Automation/Environment.ps1')
if ([string]::IsNullOrWhiteSpace($BuildDirectory)) { $BuildDirectory = Join-Path (Get-SoD2SEWorkRoot -SourceRoot $projectRoot) 'build' }

# mod.json beside each Mod is the sole source for its package name, version,
# dependency note and file list. This wrapper preserves the PowerShell entry
# point used by existing development workflows.
$arguments = @(
    (Join-Path $projectRoot 'Automation/Package/package_mo2.py'),
    '--build-dir', $BuildDirectory,
    '--output-dir', $OutputDirectory
)
if ($NativeSettingsAsset) { $arguments += @('--native-settings-asset', $NativeSettingsAsset) }
foreach ($id in $Ids) { $arguments += @('--id', $id) }
if ($IncludeFramework) { $arguments += '--include-framework' }
if ($RequireComplete) { $arguments += '--require-complete' }
if ($ValidateOnly) { $arguments += '--validate-only' }

& python @arguments
if ($LASTEXITCODE -ne 0) { throw "MO2 打包失败，退出码：$LASTEXITCODE" }
