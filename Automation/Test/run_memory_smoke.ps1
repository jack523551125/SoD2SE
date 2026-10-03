[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$GameExePath,
    [string]$BuildDirectory,
    [string]$OutputDirectory
)
$projectRoot = (Split-Path -Parent (Split-Path -Parent $PSScriptRoot))
$testRoot = Join-Path $projectRoot 'Tests'
. (Join-Path $projectRoot 'Automation/Environment.ps1')
$nativeBuildRoot = Join-Path (Get-SoD2SEWorkRoot -SourceRoot $projectRoot) 'native'


Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$source = Split-Path -Parent $testRoot
$gameExe = (Resolve-Path -LiteralPath $GameExePath).ProviderPath
$compiler = Join-Path $env:WINDIR 'Microsoft.NET\Framework64\v4.0.30319\csc.exe'
if (-not (Test-Path -LiteralPath $compiler -PathType Leaf)) { throw 'The x64 .NET Framework C# compiler is required.' }
$temporaryOutput = [string]::IsNullOrWhiteSpace($OutputDirectory)
if ($temporaryOutput) {
    $output = Join-Path ([IO.Path]::GetTempPath()) ('SoD2SE-memory-smoke-' + [Guid]::NewGuid().ToString('N'))
} else {
    $output = $ExecutionContext.SessionState.Path.GetUnresolvedProviderPathFromPSPath($OutputDirectory)
}
[IO.Directory]::CreateDirectory($output) | Out-Null
try {
    if ([string]::IsNullOrWhiteSpace($BuildDirectory)) {
        $build = Join-Path $output 'build'
        & (Join-Path $source 'Automation/Build/build.ps1') -OutputDirectory $build
        if ($LASTEXITCODE -ne 0) { throw 'Framework build failed.' }
    } else {
        $build = (Resolve-Path -LiteralPath $BuildDirectory).ProviderPath
    }
    $harness = Join-Path $output 'PluginMemorySmoke.exe'
    $core = Join-Path $build 'SoD2SE.Core.dll'
    if (-not (Test-Path -LiteralPath $core -PathType Leaf)) { throw "Missing built framework: $core" }
    $gameApi = Join-Path $build 'SoD2SE.GameApi.dll'
    if (-not (Test-Path -LiteralPath $gameApi -PathType Leaf)) { throw "Missing built game API: $gameApi" }
    $runtimeCore = Join-Path $output 'SoD2SE.Core.dll'
    if (-not [string]::Equals([IO.Path]::GetFullPath($core), [IO.Path]::GetFullPath($runtimeCore), [StringComparison]::OrdinalIgnoreCase)) {
        Copy-Item -LiteralPath $core -Destination $runtimeCore -Force
    }
    Copy-Item -LiteralPath $gameApi -Destination (Join-Path $output 'SoD2SE.GameApi.dll') -Force
    & $compiler /nologo /target:exe /platform:x64 /highentropyva+ /codepage:65001 /optimize+ /debug- /warn:4 /warnaserror+ /reference:System.dll /reference:System.Core.dll "/reference:$core" "/out:$harness" (Join-Path $testRoot 'SaveTools/PluginMemorySmoke.cs')
    if ($LASTEXITCODE -ne 0) { throw 'Memory harness build failed.' }
    & $harness $gameExe (Join-Path $build 'Plugins')
    if ($LASTEXITCODE -ne 0) { throw 'Memory smoke test failed.' }
    $threadHarness = Join-Path $output 'ThreadSafetySmoke.exe'
    & $compiler /nologo /target:exe /platform:x64 /highentropyva+ /codepage:65001 /optimize+ /debug- /warn:4 /warnaserror+ /reference:System.dll /reference:System.Core.dll "/reference:$core" "/out:$threadHarness" (Join-Path $testRoot 'SaveTools/ThreadSafetySmoke.cs')
    if ($LASTEXITCODE -ne 0) { throw 'Thread safety harness build failed.' }
    & $threadHarness
    if ($LASTEXITCODE -ne 0) { throw 'Thread safety smoke test failed.' }
    $mcmHarness = Join-Path $output 'McmSmoke.exe'
    & $compiler /nologo /target:exe /platform:x64 /highentropyva+ /codepage:65001 /optimize+ /debug- /warn:4 /warnaserror+ /reference:System.dll /reference:System.Core.dll "/reference:$core" "/out:$mcmHarness" (Join-Path $testRoot 'UI/McmSmoke.cs')
    if ($LASTEXITCODE -ne 0) { throw 'MCM harness build failed.' }
    & $mcmHarness
    if ($LASTEXITCODE -ne 0) { throw 'MCM smoke test failed.' }
    $apiHarness = Join-Path $output 'GameApiSmoke.exe'
    & $compiler /nologo /target:exe /platform:x64 /highentropyva+ /codepage:65001 /optimize+ /debug- /warn:4 /warnaserror+ /reference:System.dll /reference:System.Core.dll "/reference:$core" "/reference:$gameApi" "/out:$apiHarness" (Join-Path $testRoot 'GameApi/GameApiSmoke.cs')
    if ($LASTEXITCODE -ne 0) { throw 'Game API smoke harness build failed.' }
    & $apiHarness
    if ($LASTEXITCODE -ne 0) { throw 'Game API smoke test failed.' }
    # In-process rendering is verified separately with McmIntegrationSmoke.
    # The old external WinForms overlay is no longer part of the loader.
} finally {
    if ($temporaryOutput -and (Test-Path -LiteralPath $output)) {
        $resolvedOutput = [IO.Path]::GetFullPath($output)
        $tempRoot = [IO.Path]::GetFullPath([IO.Path]::GetTempPath()).TrimEnd('\') + '\'
        if (-not $resolvedOutput.StartsWith($tempRoot, [StringComparison]::OrdinalIgnoreCase) -or
            -not ([IO.Path]::GetFileName($resolvedOutput) -match '^SoD2SE-memory-smoke-[a-f0-9]{32}$')) {
            throw 'Refusing to remove an unexpected temporary directory.'
        }
        Remove-Item -LiteralPath $resolvedOutput -Recurse -Force
    }
}
