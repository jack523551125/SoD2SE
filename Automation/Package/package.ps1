[CmdletBinding()]
param(
    [string]$BuildDirectory = '',
    [string]$PackageDirectory = '',
    [switch]$ValidateOnly
)
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$projectRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..\..'))
. (Join-Path $projectRoot 'Automation/Environment.ps1')
$workRoot = Get-SoD2SEWorkRoot -SourceRoot $projectRoot
if ([string]::IsNullOrWhiteSpace($BuildDirectory)) { $BuildDirectory = Join-Path $workRoot 'build' }
if ([string]::IsNullOrWhiteSpace($PackageDirectory)) { $PackageDirectory = Join-Path $workRoot 'packages/SoD2SE' }

if (-not $ValidateOnly) {
    & (Join-Path $projectRoot 'Automation/Build/build.ps1') -OutputDirectory $BuildDirectory -FrameworkOnly
    if ($LASTEXITCODE -ne 0) { throw "SoD2SE framework build failed ($LASTEXITCODE)." }
}
$python = (Get-Command python -ErrorAction Stop).Source
$packager = Join-Path $projectRoot 'Automation/Package/package_mo2.py'
$arguments = @($packager, '--build-dir', $BuildDirectory, '--output-dir', $PackageDirectory, '--include-framework')
if ($ValidateOnly) { $arguments += '--validate-only' } else { $arguments += '--require-complete' }
& $python -B @arguments
if ($LASTEXITCODE -ne 0) { throw "SoD2SE framework package validation failed ($LASTEXITCODE)." }
