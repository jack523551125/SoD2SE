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
$source = [IO.Path]::GetFullPath((Join-Path $testRoot 'UI/UiFrameworkSmoke.cs'))
$compilerCandidates = @(
    (Join-Path $env:WINDIR 'Microsoft.NET\Framework64\v4.0.30319\csc.exe'),
    (Join-Path $env:WINDIR 'Microsoft.NET\Framework\v4.0.30319\csc.exe')
)
$compiler = $compilerCandidates | Where-Object { Test-Path -LiteralPath $_ -PathType Leaf } | Select-Object -First 1
if (-not $compiler) { throw '未找到 C# 编译器。' }
$temp = Join-Path ([IO.Path]::GetTempPath()) ('SoD2SE-ui-test-' + [Guid]::NewGuid().ToString('N'))
[IO.Directory]::CreateDirectory($temp) | Out-Null
try {
    $exe = Join-Path $temp 'UiFrameworkSmoke.exe'
    Copy-Item -LiteralPath (Join-Path $build 'SoD2SE.Core.dll') -Destination $temp
    & $compiler /nologo /target:exe /platform:x64 /optimize+ /warn:4 /warnaserror+ /codepage:65001 `
        /reference:System.dll /reference:System.Core.dll `
        "/reference:$(Join-Path $build 'SoD2SE.Core.dll')" /out:$exe $source
    if ($LASTEXITCODE -ne 0) { throw "UI smoke 编译失败：$LASTEXITCODE" }
    $process = Start-Process -FilePath $exe -WorkingDirectory $temp -Wait -PassThru -NoNewWindow
    if ($process.ExitCode -ne 0) { throw "UI smoke 失败：$($process.ExitCode)" }
}
finally {
    if (Test-Path -LiteralPath $temp) { Remove-Item -LiteralPath $temp -Recurse -Force }
}
