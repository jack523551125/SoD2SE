[CmdletBinding()]
param(
    [string]$OutputDirectory = ''
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
if ([string]::IsNullOrWhiteSpace($OutputDirectory)) { $OutputDirectory = Join-Path $PSScriptRoot 'compiled' }
$compilerCandidates = @(
    (Join-Path $env:WINDIR 'Microsoft.NET\Framework64\v4.0.30319\csc.exe'),
    (Join-Path $env:WINDIR 'Microsoft.NET\Framework\v4.0.30319\csc.exe')
)
$compiler = $compilerCandidates | Where-Object { Test-Path -LiteralPath $_ -PathType Leaf } | Select-Object -First 1
if (-not $compiler) { throw '未找到 Windows .NET Framework 4.x C# 编译器。' }

$out = $ExecutionContext.SessionState.Path.GetUnresolvedProviderPathFromPSPath($OutputDirectory)
$pluginOut = Join-Path $out 'Plugins'
[IO.Directory]::CreateDirectory($out) | Out-Null
[IO.Directory]::CreateDirectory($pluginOut) | Out-Null

# Version single source: FrameworkInfo.Version in Core/SoD2SE.Core.cs.  The
# assembly attributes are generated here instead of being copied into eight
# AssemblyInfo.cs files, so a DLL can no longer be stamped with another
# release's version.
$environmentScript = Join-Path $PSScriptRoot 'Environment.ps1'
if (-not (Test-Path -LiteralPath $environmentScript -PathType Leaf)) { throw "找不到共享脚本：$environmentScript" }
. $environmentScript
$frameworkVersion = Get-SoD2SEVersion -SourceRoot $PSScriptRoot
$assemblyVersion = Get-SoD2SEAssemblyVersion -Version $frameworkVersion
$generatedDirectory = Join-Path $out '.generated'
[IO.Directory]::CreateDirectory($generatedDirectory) | Out-Null
$versionSource = Join-Path $generatedDirectory 'AssemblyVersion.g.cs'
$versionAttributes = @"
using System.Reflection;

[assembly: AssemblyVersion("$assemblyVersion")]
[assembly: AssemblyFileVersion("$assemblyVersion")]
[assembly: AssemblyInformationalVersion("$frameworkVersion")]
"@
[IO.File]::WriteAllText($versionSource, $versionAttributes, [Text.UTF8Encoding]::new($true))

$common = @('/nologo','/platform:x64','/highentropyva+','/codepage:65001','/optimize+','/debug-','/warn:4','/warnaserror+','/reference:System.dll','/reference:System.Core.dll','/reference:System.Numerics.dll','/reference:System.Drawing.dll','/reference:System.Windows.Forms.dll')
$core = Join-Path $out 'SoD2SE.Core.dll'
$loader = Join-Path $out 'SoD2SE.Loader.exe'

$coreSources = @(Get-ChildItem -LiteralPath (Join-Path $PSScriptRoot 'Core') -Filter '*.cs' -File | Sort-Object Name | Select-Object -ExpandProperty FullName)
& $compiler @common '/target:library' "/out:$core" @coreSources $versionSource
if ($LASTEXITCODE -ne 0) { throw "核心框架编译失败：$LASTEXITCODE" }
$gameApi = Join-Path $out 'SoD2SE.GameApi.dll'
$gameApiSources = @(Get-ChildItem -LiteralPath (Join-Path $PSScriptRoot 'GameApi') -Filter '*.cs' -File | Sort-Object Name | Select-Object -ExpandProperty FullName)
if ($gameApiSources.Count -eq 0) { throw '找不到游戏版本 API 源码。' }
& $compiler @common "/reference:$core" '/target:library' "/out:$gameApi" @gameApiSources $versionSource
if ($LASTEXITCODE -ne 0) { throw "游戏版本 API 编译失败：$LASTEXITCODE" }
$pluginDirectories = @(Get-ChildItem -LiteralPath (Join-Path $PSScriptRoot 'Plugins') -Directory | Sort-Object Name)
foreach ($pluginDirectory in $pluginDirectories) {
    $sources = @(Get-ChildItem -LiteralPath $pluginDirectory.FullName -Filter '*.cs' -File | Sort-Object Name | Select-Object -ExpandProperty FullName)
    if ($sources.Count -eq 0) { continue }
    $plugin = Join-Path $pluginOut ($pluginDirectory.Name + '.dll')
    & $compiler @common "/reference:$core" "/reference:$gameApi" '/target:library' "/out:$plugin" @sources $versionSource
    if ($LASTEXITCODE -ne 0) { throw "插件 $($pluginDirectory.Name) 编译失败：$LASTEXITCODE" }
    Write-Output "插件：$plugin"
}
$loaderSources = @(Get-ChildItem -LiteralPath (Join-Path $PSScriptRoot 'Loader') -Filter '*.cs' -File | Sort-Object Name | Select-Object -ExpandProperty FullName)
& $compiler @common "/reference:$core" "/reference:$gameApi" '/target:winexe' "/out:$loader" @loaderSources $versionSource
if ($LASTEXITCODE -ne 0) { throw "加载器编译失败：$LASTEXITCODE" }

# One native build produces both components and proves it wrote them, so a
# failed melee compile can no longer be masked by last session's DLL.
& (Join-Path $PSScriptRoot 'Native\build_native.ps1') -OutputDirectory (Join-Path $pluginOut 'Mcm') -MeleeOutputDirectory (Join-Path $pluginOut 'MeleeSpeed')
if ($LASTEXITCODE -ne 0) { throw '原生组件构建失败。' }

Write-Output "SoD2SE.Core.dll：$core"
Write-Output "SoD2SE.Loader.exe：$loader"
Write-Output '构建过程没有启动游戏，也没有修改游戏文件。'
