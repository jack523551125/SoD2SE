[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$BuildDirectory,
    [Parameter(Mandatory = $true)][string]$McmSettingsAsset,
    [string]$OutputDirectory = (Join-Path $PSScriptRoot '..\..\outputs')
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

# Compatibility entry point. Versions and payloads come from each Mod's
# mod.json and the supplied build, never from this script or an MO2 install.
& (Join-Path $PSScriptRoot 'package_mo2.ps1') `
    -BuildDirectory $BuildDirectory `
    -OutputDirectory $OutputDirectory `
    -NativeSettingsAsset $McmSettingsAsset `
    -Ids @('Mcm', 'NativeModSettingsEntry')
if ($LASTEXITCODE -ne 0) { throw "MCM 打包失败，退出码：$LASTEXITCODE" }
