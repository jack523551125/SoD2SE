[CmdletBinding()]
param([string]$OutputDirectory = '')
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$projectRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..\..'))
if ([string]::IsNullOrWhiteSpace($OutputDirectory)) {
    . (Join-Path $projectRoot 'Automation/Environment.ps1')
    $OutputDirectory = Join-Path (Get-SoD2SEWorkRoot -SourceRoot $projectRoot) 'products/SoD2SE'
}
& (Join-Path $PSScriptRoot 'check.ps1') -OutputDirectory $OutputDirectory
if ($LASTEXITCODE -ne 0) { throw 'SoD2SE framework check failed.' }
$output = [IO.Path]::GetFullPath($ExecutionContext.SessionState.Path.GetUnresolvedProviderPathFromPSPath($OutputDirectory))
$nativeBuild = Join-Path $output 'native-shared'
& cmake -S (Join-Path $projectRoot 'Native') -B $nativeBuild -G 'Visual Studio 17 2022' -A x64
if ($LASTEXITCODE -ne 0) { throw "SoD2SE shared native configure failed ($LASTEXITCODE)." }
& cmake --build $nativeBuild --config Release --target CharacterIdentifierCodecTest PinnedImageTest --parallel
if ($LASTEXITCODE -ne 0) { throw "SoD2SE shared native test build failed ($LASTEXITCODE)." }
& (Join-Path $nativeBuild 'Release/CharacterIdentifierCodecTest.exe')
if ($LASTEXITCODE -ne 0) { throw 'CharacterIdentifierCodecTest failed.' }
$pinnedImage = Join-Path $nativeBuild 'Release/PinnedImageTest.exe'
$hash = (Get-FileHash -LiteralPath $pinnedImage -Algorithm SHA256).Hash
& $pinnedImage $hash
if ($LASTEXITCODE -ne 0) { throw 'PinnedImageTest failed for the inert test executable.' }

$compiler = @(
    (Join-Path $env:WINDIR 'Microsoft.NET/Framework64/v4.0.30319/csc.exe'),
    (Join-Path $env:WINDIR 'Microsoft.NET/Framework/v4.0.30319/csc.exe')) |
    Where-Object { Test-Path -LiteralPath $_ -PathType Leaf } | Select-Object -First 1
if (-not $compiler) { throw 'Windows .NET Framework 4.x C# compiler (csc.exe) was not found.' }
$testDirectory = Join-Path $output '.tests'
[IO.Directory]::CreateDirectory($testDirectory) | Out-Null
foreach ($name in @('SoD2SE.Core.dll','SoD2SE.GameApi.dll')) {
    Copy-Item -LiteralPath (Join-Path $output $name) -Destination $testDirectory -Force
}
$common = @('/nologo','/platform:x64','/codepage:65001','/warnaserror+',
    '/reference:System.dll','/reference:System.Core.dll','/reference:System.Numerics.dll',
    '/reference:System.Drawing.dll','/reference:System.Windows.Forms.dll',
    ("/reference:" + (Join-Path $output 'SoD2SE.Core.dll')),
    ("/reference:" + (Join-Path $output 'SoD2SE.GameApi.dll')))
foreach ($test in @('Tests/GameApi/GameApiSmoke.cs','Tests/Core/UiFrameworkSmoke.cs')) {
    $source = Join-Path $projectRoot $test
    $exe = Join-Path $testDirectory ([IO.Path]::GetFileNameWithoutExtension($source) + '.exe')
    & $compiler @common ("/out:" + $exe) $source
    if ($LASTEXITCODE -ne 0) { throw "Managed test compile failed: $test ($LASTEXITCODE)." }
    Push-Location $testDirectory
    try { & $exe; if ($LASTEXITCODE -ne 0) { throw "Managed test failed: $test ($LASTEXITCODE)." } }
    finally { Pop-Location }
}
$python = (Get-Command python -ErrorAction Stop).Source
Push-Location $projectRoot
try {
    & $python -B -m pytest -q -p no:cacheprovider Tests/Packaging
    if ($LASTEXITCODE -ne 0) { throw "SoD2SE packaging/source-layout tests failed ($LASTEXITCODE)." }
}
finally { Pop-Location }
Write-Output 'PASS: SoD2SE offline framework, shared-native, managed smoke and packaging tests; no game launched.'
