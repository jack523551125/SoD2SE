[CmdletBinding()]
param(
    [string]$BuildDirectory = (Join-Path $PSScriptRoot 'compiled'),
    [string]$OutputDirectory = (Join-Path $PSScriptRoot '..\..\outputs'),
    [string]$NativeSettingsAsset = '',
    [string[]]$Ids = @(),
    [switch]$IncludeFramework,
    [switch]$RequireComplete,
    [switch]$ValidateOnly
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

# mod.json beside each Mod is the sole source for its package name, version,
# dependency note and file list. This wrapper preserves the PowerShell entry
# point used by existing development workflows.
$arguments = @(
    (Join-Path $PSScriptRoot 'package_mo2.py'),
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
