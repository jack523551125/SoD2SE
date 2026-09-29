[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$SettingsAsset,
    [string]$BuildDirectory = (Join-Path $PSScriptRoot 'compiled'),
    [string]$OutputDirectory = (Join-Path $PSScriptRoot '..\..\outputs'),
    [string]$GameRoot = ''
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

if ($GameRoot) {
    throw '不再从游戏或已安装 MO2 Mod 提取构建文件。请先运行 build.ps1，再传入 BuildDirectory。'
}

# Compatibility entry point. The common packager reads current build output
# and per-Mod manifests; it never copies a previously installed native DLL.
& (Join-Path $PSScriptRoot 'package_mo2.ps1') `
    -BuildDirectory $BuildDirectory `
    -OutputDirectory $OutputDirectory `
    -NativeSettingsAsset $SettingsAsset `
    -Ids @('UnlimitedFollowers', 'UnlimitedCommunity', 'MeleeSpeed', 'NativeModSettingsEntry', 'SkipStartupIntro')
if ($LASTEXITCODE -ne 0) { throw "状态页打包失败，退出码：$LASTEXITCODE" }
