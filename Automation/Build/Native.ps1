[CmdletBinding()]
param(
    [string]$OutputDirectory = '',
    [string]$MeleeOutputDirectory = '',
    [string]$GrowthOutputDirectory = '',
    [string]$BuildDirectory = '',
    [string[]]$Components = @(),
    [string]$SourceDirectory = '',
    [string]$Sod2seRoot = ''
)
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$projectRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..\..'))
if ([string]::IsNullOrWhiteSpace($Sod2seRoot)) { $Sod2seRoot = $env:SOD2SE_ROOT }
if ([string]::IsNullOrWhiteSpace($Sod2seRoot)) { $Sod2seRoot = $projectRoot }
$Sod2seRoot = [IO.Path]::GetFullPath($Sod2seRoot)
if ([string]::IsNullOrWhiteSpace($SourceDirectory)) { $SourceDirectory = Join-Path $projectRoot 'Native' }
$SourceDirectory = [IO.Path]::GetFullPath($SourceDirectory)
if (-not (Test-Path -LiteralPath (Join-Path $SourceDirectory 'CMakeLists.txt') -PathType Leaf)) { throw "Missing CMakeLists.txt: $SourceDirectory" }
if ([string]::IsNullOrWhiteSpace($BuildDirectory)) {
    . (Join-Path $projectRoot 'Automation/Environment.ps1')
    $BuildDirectory = Join-Path (Get-SoD2SEWorkRoot -SourceRoot $projectRoot) 'native'
}
$BuildDirectory = [IO.Path]::GetFullPath($BuildDirectory)
[IO.Directory]::CreateDirectory($BuildDirectory) | Out-Null
$targets = @{
    Mcm = [pscustomobject]@{ Name='SoD2McmNative'; File='SoD2SE.Mcm.Native.dll'; Destination=$OutputDirectory }
    MeleeSpeed = [pscustomobject]@{ Name='SoD2MeleeNative'; File='SoD2SE.MeleeSpeed.Native.dll'; Destination=$MeleeOutputDirectory }
    Roguelite = [pscustomobject]@{ Name='SoD2GrowthNative'; File='SoD2SE.Growth.Native.dll'; Destination=$GrowthOutputDirectory }
}
if ($Components.Count -eq 0) { $Components = @('Mcm','MeleeSpeed','Roguelite') }
$selected = @()
foreach ($component in $Components) {
    if (-not $targets.ContainsKey($component)) { throw "Unknown native component: $component" }
    if ([string]::IsNullOrWhiteSpace($targets[$component].Destination)) { throw "Output directory is required for $component" }
    $selected += $targets[$component]
}
$cmakeArgs = @('-S', $SourceDirectory, '-B', $BuildDirectory, '-G', 'Visual Studio 17 2022', '-A', 'x64', "-DSOD2SE_ROOT=$Sod2seRoot")
& cmake @cmakeArgs
if ($LASTEXITCODE -ne 0) { throw "CMake configure failed ($LASTEXITCODE)." }
foreach ($target in $selected) {
    $product = Join-Path (Join-Path $BuildDirectory 'Release') $target.File
    Remove-Item -LiteralPath $product -Force -ErrorAction SilentlyContinue
    & cmake --build $BuildDirectory --config Release --target $target.Name --parallel
    if ($LASTEXITCODE -ne 0) { throw "Native target $($target.Name) failed ($LASTEXITCODE)." }
    if (-not (Test-Path -LiteralPath $product -PathType Leaf)) { throw "Native target did not produce $product" }
    $destination = [IO.Path]::GetFullPath($ExecutionContext.SessionState.Path.GetUnresolvedProviderPathFromPSPath($target.Destination))
    [IO.Directory]::CreateDirectory($destination) | Out-Null
    Copy-Item -LiteralPath $product -Destination $destination -Force
    Write-Output "Native product: $(Join-Path $destination $target.File)"
}
