[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$BuildDirectory
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$build = $ExecutionContext.SessionState.Path.GetUnresolvedProviderPathFromPSPath($BuildDirectory)
$compilerCandidates = @(
    (Join-Path $env:WINDIR 'Microsoft.NET\Framework64\v4.0.30319\csc.exe'),
    (Join-Path $env:WINDIR 'Microsoft.NET\Framework\v4.0.30319\csc.exe')
)
$compiler = $compilerCandidates | Where-Object { Test-Path -LiteralPath $_ -PathType Leaf } | Select-Object -First 1
if (-not $compiler) { throw '未找到 C# 编译器。' }
$temp = Join-Path ([IO.Path]::GetTempPath()) ('SoD2SE-headless-smoke-' + [Guid]::NewGuid().ToString('N'))
[IO.Directory]::CreateDirectory($temp) | Out-Null

try {
    $core = Join-Path $build 'SoD2SE.Core.dll'
    $gameApi = Join-Path $build 'SoD2SE.GameApi.dll'
    foreach ($dependency in @($core, $gameApi)) {
        if (-not (Test-Path -LiteralPath $dependency -PathType Leaf)) { throw "缺少构建依赖：$dependency" }
        Copy-Item -LiteralPath $dependency -Destination $temp
    }

    $common = @('/nologo', '/target:exe', '/platform:x64', '/optimize+', '/warn:4', '/warnaserror+', '/codepage:65001',
        '/reference:System.dll', '/reference:System.Core.dll', "/reference:$core")
    $mcmExe = Join-Path $temp 'McmSmoke.exe'
    & $compiler @common "/out:$mcmExe" (Join-Path $PSScriptRoot 'McmSmoke.cs')
    if ($LASTEXITCODE -ne 0) { throw "MCM smoke 编译失败：$LASTEXITCODE" }
    & $mcmExe
    if ($LASTEXITCODE -ne 0) { throw "MCM smoke 失败：$LASTEXITCODE" }

    $apiExe = Join-Path $temp 'GameApiSmoke.exe'
    & $compiler @common "/reference:$gameApi" "/out:$apiExe" (Join-Path $PSScriptRoot 'GameApiSmoke.cs')
    if ($LASTEXITCODE -ne 0) { throw "Game API smoke 编译失败：$LASTEXITCODE" }
    & $apiExe
    if ($LASTEXITCODE -ne 0) { throw "Game API smoke 失败：$LASTEXITCODE" }
}
finally {
    if (Test-Path -LiteralPath $temp) {
        $resolvedTemp = [IO.Path]::GetFullPath($temp)
        $tempRoot = [IO.Path]::GetFullPath([IO.Path]::GetTempPath()).TrimEnd('\') + '\'
        if (-not $resolvedTemp.StartsWith($tempRoot, [StringComparison]::OrdinalIgnoreCase) -or
            -not ([IO.Path]::GetFileName($resolvedTemp) -match '^SoD2SE-headless-smoke-[a-f0-9]{32}$')) {
            throw '拒绝删除临时目录之外的路径。'
        }
        Remove-Item -LiteralPath $resolvedTemp -Recurse -Force
    }
}
