[CmdletBinding()]
param(
    [Parameter(Mandatory=$true)][string]$BuildDirectory,
    [Parameter(Mandatory=$true)][string]$NativeRenderTest,
    [string]$OutputDirectory = '',
    [ValidateSet('growth','settings')][string]$Mode = 'growth'
)
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
if ([string]::IsNullOrWhiteSpace($OutputDirectory)) {
    # The preview folder follows the framework version instead of a literal, so
    # screenshots never land in an older release's directory.
    . (Join-Path $PSScriptRoot '..\Environment.ps1')
    $version = Get-SoD2SEVersion -SourceRoot (Join-Path $PSScriptRoot '..')
    $OutputDirectory = Join-Path $PSScriptRoot "..\..\..\outputs\SoD2SE-$version\ui-preview"
}
$build = (Resolve-Path -LiteralPath $BuildDirectory).ProviderPath
$native = (Resolve-Path -LiteralPath $NativeRenderTest).ProviderPath
$output = $ExecutionContext.SessionState.Path.GetUnresolvedProviderPathFromPSPath($OutputDirectory)
[IO.Directory]::CreateDirectory($output) | Out-Null
# The render test stops as soon as it sees a stop.request file, so a leftover
# from an earlier run would make the new host exit before it can draw.
foreach ($stale in 'stop.request','capture.request','input.request','resize.request','menu.bmp') {
    $path = Join-Path $output $stale
    if (Test-Path -LiteralPath $path -PathType Leaf) { Remove-Item -LiteralPath $path -Force }
}
$compilerCandidates = @(
    (Join-Path $env:WINDIR 'Microsoft.NET\Framework64\v4.0.30319\csc.exe'),
    (Join-Path $env:WINDIR 'Microsoft.NET\Framework\v4.0.30319\csc.exe')
)
$compiler = $compilerCandidates | Where-Object { Test-Path -LiteralPath $_ -PathType Leaf } | Select-Object -First 1
if (-not $compiler) { throw '未找到 C# 编译器。' }
$temp = Join-Path ([IO.Path]::GetTempPath()) ('SoD2SE-growth-preview-' + [Guid]::NewGuid().ToString('N'))
[IO.Directory]::CreateDirectory($temp) | Out-Null
try {
    $exe = Join-Path $temp 'GrowthScreenPreview.exe'
    Copy-Item -LiteralPath (Join-Path $build 'SoD2SE.Core.dll'), (Join-Path $build 'SoD2SE.GameApi.dll'), (Join-Path $build 'Plugins\Roguelite.dll') -Destination $temp
    & $compiler /nologo /target:exe /platform:x64 /optimize+ /warn:4 /warnaserror+ /codepage:65001 `
        /reference:System.dll /reference:System.Core.dll /reference:System.Numerics.dll `
        "/reference:$(Join-Path $build 'SoD2SE.Core.dll')" "/reference:$(Join-Path $build 'SoD2SE.GameApi.dll')" `
        "/reference:$(Join-Path $build 'Plugins\Roguelite.dll')" /out:$exe (Join-Path $PSScriptRoot 'GrowthScreenPreview.cs')
    if ($LASTEXITCODE -ne 0) { throw "成长界面预览编译失败：$LASTEXITCODE" }
    # 1080p-sized client area so the screenshot shows what a normal session
    # sees, not the small verification window.
    $process = Start-Process -FilePath $exe -WorkingDirectory $temp -ArgumentList @((Join-Path $build ''), $native, $output, '1920x1240', $Mode) -Wait -PassThru -NoNewWindow
    if ($process.ExitCode -ne 0) { throw "成长界面预览失败：$($process.ExitCode)" }
    $name = if ($Mode -eq 'settings') { 'mcm-settings.png' } else { 'growth-screen.png' }
    $bmp = Join-Path $output 'menu.bmp'
    if (-not (Test-Path -LiteralPath $bmp -PathType Leaf)) { throw "缺少截图：$bmp" }
    Add-Type -AssemblyName System.Drawing
    $image = [System.Drawing.Image]::FromFile($bmp)
    try { $image.Save((Join-Path $output $name), [System.Drawing.Imaging.ImageFormat]::Png) }
    finally { $image.Dispose() }
    Write-Output ("截图：" + (Join-Path $output $name))
}
finally {
    if (Test-Path -LiteralPath $temp) { Remove-Item -LiteralPath $temp -Recurse -Force }
}
