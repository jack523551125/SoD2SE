[CmdletBinding()]
param(
    [Parameter(Mandatory=$true)][string]$BuildDirectory
)
$projectRoot = (Split-Path -Parent (Split-Path -Parent $PSScriptRoot))
$testRoot = Join-Path $projectRoot 'Tests'
. (Join-Path $projectRoot 'Automation/Environment.ps1')
$nativeBuildRoot = Join-Path (Get-SoD2SEWorkRoot -SourceRoot $projectRoot) 'native'

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
# Resolve through the PowerShell provider so a relative path means what the
# caller typed, not what the host process happens to have as its cwd.
$build = $ExecutionContext.SessionState.Path.GetUnresolvedProviderPathFromPSPath($BuildDirectory)
$source = [IO.Path]::GetFullPath((Join-Path $testRoot 'Growth/RogueliteSmoke.cs'))
$compilerCandidates = @(
    (Join-Path $env:WINDIR 'Microsoft.NET\Framework64\v4.0.30319\csc.exe'),
    (Join-Path $env:WINDIR 'Microsoft.NET\Framework\v4.0.30319\csc.exe')
)
$compiler = $compilerCandidates | Where-Object { Test-Path -LiteralPath $_ -PathType Leaf } | Select-Object -First 1
if (-not $compiler) { throw '未找到 C# 编译器。' }
$temp = Join-Path ([IO.Path]::GetTempPath()) ('SoD2SE-roguelite-test-' + [Guid]::NewGuid().ToString('N'))
[IO.Directory]::CreateDirectory($temp) | Out-Null
try {
    $exe = Join-Path $temp 'RogueliteSmoke.exe'
    Copy-Item -LiteralPath (Join-Path $build 'SoD2SE.Core.dll'), (Join-Path $build 'SoD2SE.GameApi.dll'), (Join-Path $build 'Plugins\Roguelite.dll') -Destination $temp
    Copy-Item -LiteralPath (Join-Path $nativeBuildRoot 'Release/GrowthUiTest.exe') -Destination $temp
    & $compiler /nologo /platform:x64 /optimize+ /warn:4 /warnaserror+ /codepage:65001 `
        /reference:System.dll /reference:System.Core.dll /reference:System.Numerics.dll `
        "/reference:$(Join-Path $build 'SoD2SE.Core.dll')" "/reference:$(Join-Path $build 'SoD2SE.GameApi.dll')" `
        "/reference:$(Join-Path $build 'Plugins\Roguelite.dll')" /out:$exe $source (Join-Path $testRoot 'Growth/GrowthAdapterSmoke.cs') (Join-Path $testRoot 'Growth/GrowthPageSmoke.cs')
    if ($LASTEXITCODE -ne 0) { throw "Roguelite smoke 编译失败：$LASTEXITCODE" }
    $process = Start-Process -FilePath $exe -WorkingDirectory $temp -Wait -PassThru -NoNewWindow
    if ($process.ExitCode -ne 0) { throw "Roguelite smoke 失败：$($process.ExitCode)" }
}
finally {
    if (Test-Path -LiteralPath $temp) {
        $resolvedTestDirectory = [IO.Path]::GetFullPath($temp)
        $testTempRoot = [IO.Path]::GetFullPath([IO.Path]::GetTempPath()).TrimEnd('\') + '\'
        if (-not $resolvedTestDirectory.StartsWith($testTempRoot, [StringComparison]::OrdinalIgnoreCase) -or
            -not ([IO.Path]::GetFileName($resolvedTestDirectory) -match '^SoD2SE-roguelite-test-[a-f0-9]{32}$')) {
            throw '拒绝删除测试临时目录之外的路径。'
        }
        Remove-Item -LiteralPath $resolvedTestDirectory -Recurse -Force
    }
}
