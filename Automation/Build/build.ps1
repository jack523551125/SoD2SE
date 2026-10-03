[CmdletBinding()]
param(
    [string]$OutputDirectory = '',
    [string[]]$Ids = @(),
    [switch]$FrameworkOnly,
    [switch]$NoLoader,
    [string]$PluginSourceDirectory = '',
    [string]$PluginId = '',
    [string]$NativeSourceDirectory = '',
    [string]$Sod2seRoot = ''
)
$projectRoot = (Split-Path -Parent (Split-Path -Parent $PSScriptRoot))


Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
. (Join-Path $projectRoot 'Automation/Environment.ps1')
if ([string]::IsNullOrWhiteSpace($OutputDirectory)) { $OutputDirectory = Join-Path (Get-SoD2SEWorkRoot -SourceRoot $projectRoot) 'build' }
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

# FrameworkInfo.Version owns framework binaries. Each Plugins/<Id>/mod.json
# owns that plugin's assembly and MO2 package version.
$environmentScript = Join-Path $projectRoot 'Automation/Environment.ps1'
if (-not (Test-Path -LiteralPath $environmentScript -PathType Leaf)) { throw "找不到共享脚本：$environmentScript" }
. $environmentScript
$frameworkVersion = Get-SoD2SEVersion -SourceRoot $projectRoot
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

$coreSources = @(Get-ChildItem -LiteralPath (Join-Path $projectRoot 'Core') -Filter '*.cs' -File -Recurse | Sort-Object Name | Select-Object -ExpandProperty FullName)
& $compiler @common '/target:library' "/out:$core" @coreSources $versionSource
if ($LASTEXITCODE -ne 0) { throw "核心框架编译失败：$LASTEXITCODE" }
$gameApi = Join-Path $out 'SoD2SE.GameApi.dll'
$gameApiSources = @(Get-ChildItem -LiteralPath (Join-Path $projectRoot 'GameApi') -Filter '*.cs' -File | Sort-Object Name | Select-Object -ExpandProperty FullName)
if ($gameApiSources.Count -eq 0) { throw '找不到游戏版本 API 源码。' }
& $compiler @common "/reference:$core" '/target:library' "/out:$gameApi" @gameApiSources $versionSource
if ($LASTEXITCODE -ne 0) { throw "游戏版本 API 编译失败：$LASTEXITCODE" }
$pluginDirectories = @()
if (-not [string]::IsNullOrWhiteSpace($PluginSourceDirectory)) {
    $resolvedPluginSource = $ExecutionContext.SessionState.Path.GetUnresolvedProviderPathFromPSPath($PluginSourceDirectory)
    if (-not (Test-Path -LiteralPath $resolvedPluginSource -PathType Container)) { throw "找不到产品源码目录：$resolvedPluginSource" }
    if ([string]::IsNullOrWhiteSpace($PluginId)) { throw 'PluginId is required with PluginSourceDirectory.' }
    $pluginDirectories = @([pscustomobject]@{ Name=$PluginId; FullName=$resolvedPluginSource })
} else {
    $legacyPluginRoot = Join-Path $projectRoot 'Plugins'
    if (Test-Path -LiteralPath $legacyPluginRoot -PathType Container) {
        $pluginDirectories = @(Get-ChildItem -LiteralPath $legacyPluginRoot -Directory | Sort-Object Name)
    }
}
foreach ($pluginDirectory in $pluginDirectories) {
    if ($FrameworkOnly -or ($Ids.Count -gt 0 -and $pluginDirectory.Name -notin $Ids)) { continue }
    $sources = @(Get-ChildItem -LiteralPath $pluginDirectory.FullName -Filter '*.cs' -File | Sort-Object Name | Select-Object -ExpandProperty FullName)
    if ($sources.Count -eq 0) { continue }
    $manifestPath = Join-Path $pluginDirectory.FullName 'mod.json'
    if (-not (Test-Path -LiteralPath $manifestPath -PathType Leaf)) { throw "插件缺少 mod.json：$manifestPath" }
    $manifest = Get-Content -LiteralPath $manifestPath -Raw -Encoding UTF8 | ConvertFrom-Json
    $pluginIdForBuild = if ([string]::IsNullOrWhiteSpace($PluginId)) { $pluginDirectory.Name } else { $PluginId }
    if ($manifest.id -cne $pluginIdForBuild) { throw "插件 ID 与目录 metadata 不一致：$manifestPath" }
    $pluginVersion = [string]$manifest.version
    if ($pluginVersion -cnotmatch '^\d+\.\d+\.\d+(?:-[A-Za-z0-9.-]+)?$') { throw "插件版本无效：$manifestPath" }
    $pluginAssemblyVersion = Get-SoD2SEAssemblyVersion -Version $pluginVersion
    $pluginVersionSource = Join-Path $generatedDirectory ($pluginIdForBuild + '.AssemblyVersion.g.cs')
    $pluginVersionAttributes = @"
using System.Reflection;

[assembly: AssemblyVersion("$pluginAssemblyVersion")]
[assembly: AssemblyFileVersion("$pluginAssemblyVersion")]
[assembly: AssemblyInformationalVersion("$pluginVersion")]
"@
    [IO.File]::WriteAllText($pluginVersionSource, $pluginVersionAttributes, [Text.UTF8Encoding]::new($true))
    $plugin = Join-Path $pluginOut ($pluginIdForBuild + '.dll')
    & $compiler @common "/reference:$core" "/reference:$gameApi" '/target:library' "/out:$plugin" @sources $pluginVersionSource
    if ($LASTEXITCODE -ne 0) { throw "插件 $($pluginDirectory.Name) 编译失败：$LASTEXITCODE" }
    Write-Output "插件：$plugin"
}
if (-not $NoLoader) {
$loaderSources = @(Get-ChildItem -LiteralPath (Join-Path $projectRoot 'Loader') -Filter '*.cs' -File | Sort-Object Name | Select-Object -ExpandProperty FullName)
& $compiler @common "/reference:$core" "/reference:$gameApi" '/target:winexe' "/out:$loader" @loaderSources $versionSource
if ($LASTEXITCODE -ne 0) { throw "加载器编译失败：$LASTEXITCODE" }

}

# One native build produces all native components and proves it wrote them, so a
# failed melee compile can no longer be masked by last session's DLL.
$components = @()
if (-not $FrameworkOnly -and -not [string]::IsNullOrWhiteSpace($NativeSourceDirectory)) {
    $componentNames = @{ Mcm='Mcm'; MeleeSpeed='MeleeSpeed'; Roguelite='Roguelite' }
    if ($PluginId -and $componentNames.ContainsKey($PluginId)) { $components = @($componentNames[$PluginId]) }
    elseif ($Ids.Count -gt 0) { $components = @($Ids | Where-Object { $componentNames.ContainsKey($_) } | ForEach-Object { $componentNames[$_] }) }
}
if ($components.Count -gt 0) {
    $nativeArguments = @{ OutputDirectory=(Join-Path $pluginOut 'Mcm'); MeleeOutputDirectory=(Join-Path $pluginOut 'MeleeSpeed'); GrowthOutputDirectory=(Join-Path $pluginOut 'Roguelite'); Components=$components }
    if (-not [string]::IsNullOrWhiteSpace($NativeSourceDirectory)) {
        $nativeArguments.SourceDirectory = $ExecutionContext.SessionState.Path.GetUnresolvedProviderPathFromPSPath($NativeSourceDirectory)
        $nativeArguments.BuildDirectory = Join-Path $out 'native-build'
    }
    $nativeArguments.Sod2seRoot = $projectRoot
    & (Join-Path $projectRoot 'Automation/Build/Native.ps1') @nativeArguments
    if ($LASTEXITCODE -ne 0) { throw '原生组件构建失败。' }
}

Write-Output "SoD2SE.Core.dll：$core"
if (-not $NoLoader) { Write-Output "SoD2SE.Loader.exe：$loader" }
Write-Output '构建过程没有启动游戏，也没有修改游戏文件。'
