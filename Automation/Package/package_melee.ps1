[CmdletBinding()]
param([string]$OutputDirectory = '')
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

# The melee-only preview used to carry its own copy of the version, the ZIP
# names and a Docs folder.  Both the version and the "no Docs in a mod package"
# rule now live in package_mo2.ps1, so this script only forwards.
$forwarder = Join-Path $PSScriptRoot 'package_mo2.ps1'
if (-not (Test-Path -LiteralPath $forwarder -PathType Leaf)) { throw "找不到 MO2 打包脚本：$forwarder" }

. (Join-Path $PSScriptRoot 'Environment.ps1')
$version = Get-SoD2SEVersion -SourceRoot $PSScriptRoot

$arguments = @{}
if (-not [string]::IsNullOrWhiteSpace($OutputDirectory)) { $arguments['OutputDirectory'] = $OutputDirectory }
& $forwarder @arguments
if ($LASTEXITCODE -ne 0) { throw "MO2 打包失败：$LASTEXITCODE" }

Write-Output "近战攻速包已包含在 SoD2SE-MeleeSpeed-MO2-v$version.zip；框架包为 SoD2SE-Framework-MO2-v$version.zip。"