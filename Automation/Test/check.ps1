[CmdletBinding()]
param([string]$OutputDirectory = '')
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$projectRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..\..'))
if ([string]::IsNullOrWhiteSpace($OutputDirectory)) {
    . (Join-Path $projectRoot 'Automation/Environment.ps1')
    $OutputDirectory = Join-Path (Get-SoD2SEWorkRoot -SourceRoot $projectRoot) 'products/SoD2SE'
}
& (Join-Path $projectRoot 'Automation/Build/build.ps1') -OutputDirectory $OutputDirectory -FrameworkOnly
if ($LASTEXITCODE -ne 0) { throw "SoD2SE framework build/check failed ($LASTEXITCODE)." }
Write-Output 'PASS: SoD2SE Core/GameApi framework build; no game process or files used.'
