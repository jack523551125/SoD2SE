[CmdletBinding()]
param(
    [Parameter(Mandatory=$true)][string]$BuildDirectory,
    [Parameter(Mandatory=$true)][string]$NativeRenderTest
)
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$build = (Resolve-Path -LiteralPath $BuildDirectory).ProviderPath
$native = (Resolve-Path -LiteralPath $NativeRenderTest).ProviderPath
$compiler = Join-Path $env:WINDIR 'Microsoft.NET\Framework64\v4.0.30319\csc.exe'
$temp = Join-Path ([IO.Path]::GetTempPath()) ('SoD2SE-mcm-integration-' + [Guid]::NewGuid().ToString('N'))
[IO.Directory]::CreateDirectory($temp) | Out-Null
try {
    $exe = Join-Path $temp 'McmIntegrationSmoke.exe'
    Copy-Item -LiteralPath (Join-Path $build 'SoD2SE.Core.dll') -Destination $temp
    Copy-Item -LiteralPath (Join-Path $build 'SoD2SE.GameApi.dll') -Destination $temp
    & $compiler /nologo /target:exe /platform:x64 /highentropyva+ /codepage:65001 /optimize+ /debug- /warn:4 /warnaserror+ /reference:System.dll /reference:System.Core.dll `
        "/reference:$(Join-Path $build 'SoD2SE.Core.dll')" /out:$exe (Join-Path $PSScriptRoot 'McmIntegrationSmoke.cs')
    if ($LASTEXITCODE -ne 0) { throw "MCM integration harness build failed: $LASTEXITCODE" }
    $process = Start-Process -FilePath $exe -WorkingDirectory $temp -ArgumentList @((Join-Path $build ''), $native, $temp) -Wait -PassThru -NoNewWindow
    if ($process.ExitCode -ne 0) { throw "MCM integration smoke failed: $($process.ExitCode)" }
}
finally {
    if (Test-Path -LiteralPath $temp) { Remove-Item -LiteralPath $temp -Recurse -Force }
}
