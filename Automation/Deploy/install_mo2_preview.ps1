[CmdletBinding()]
param(
    [string]$MoDataRoot = '',
    [Parameter(Mandatory=$true)][string]$PackageDirectory,
    [string]$GameDirectory = '',
    [string]$ProfileName = 'Default'
)
$projectRoot = (Split-Path -Parent (Split-Path -Parent $PSScriptRoot))

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

# Shared lookups: the version comes from Core/SoD2SE.Core.cs, and both install
# roots are resolved (parameter, environment variable, hint file, discovery)
# instead of being pinned to one machine.
$environmentScript = Join-Path $projectRoot 'Automation/Environment.ps1'
if (-not (Test-Path -LiteralPath $environmentScript -PathType Leaf)) { throw "找不到共享脚本：$environmentScript" }
. $environmentScript

if (Get-Process StateOfDecay2*,SoD2SE.Loader -ErrorAction SilentlyContinue) {
    throw '请先退出游戏与 SoD2SE 加载器；游戏正在使用的文件不会被替换。'
}

$instance = Resolve-Mo2DataRoot -MoDataRoot $MoDataRoot -HintFileDirectory $projectRoot
if ([string]::IsNullOrWhiteSpace($GameDirectory)) {
    $game = Get-SoD2GameDirectoryFromExecutable -GameExePath (Resolve-SoD2GameExecutable -HintFileDirectory $projectRoot)
} else {
    $game = [IO.Path]::GetFullPath((Resolve-Path -LiteralPath $GameDirectory).ProviderPath)
}
$mods = [IO.Path]::GetFullPath((Join-Path $instance 'mods'))
$packages = [IO.Path]::GetFullPath((Resolve-Path -LiteralPath $PackageDirectory).ProviderPath)
if (-not (Test-Path -LiteralPath $mods -PathType Container)) { throw "找不到 MO2 mods 目录：$mods" }
if (-not (Test-Path -LiteralPath (Join-Path $game 'StateOfDecay2.exe') -PathType Leaf)) { throw "找不到游戏根目录：$game" }

$version = Get-SoD2SEVersion -SourceRoot $projectRoot

# Directory names match the name= field inside each meta.ini, which is what
# MO2 itself uses when the archive is installed from the downloads pane.
$entries = @(
    @{ Zip = "SoD2SE-Mcm-MO2-v$version.zip"; Directory = '模组配置菜单 - Mod Configuration Menu' },
    @{ Zip = "SoD2SE-MeleeSpeed-MO2-v$version.zip"; Directory = '近战攻速 - Melee Attack Speed' },
    @{ Zip = "SoD2SE-Roguelite-MO2-v$version.zip"; Directory = '幸存者成长 - Survivor Roguelite' },
    @{ Zip = "SoD2SE-UnlimitedFollowers-MO2-v$version.zip"; Directory = '无限随从 - Unlimited Followers' },
    @{ Zip = "SoD2SE-UnlimitedCommunity-MO2-v$version.zip"; Directory = '社区招募无上限 - Unlimited Community Recruitment' }
)
# Older installs used English folder names; they are removed so the profile
# cannot keep loading a superseded copy.
$legacy = @('SoD2SE MCM','SoD2SE Melee Speed','SoD2SE Survivor Roguelite','SoD2SE Unlimited Followers','SoD2SE Unlimited Community')

$temp = Join-Path ([IO.Path]::GetTempPath()) ('SoD2SE-MO2-install-' + [Guid]::NewGuid().ToString('N'))
[IO.Directory]::CreateDirectory($temp) | Out-Null
try {
    $frameworkZip = Join-Path $packages "SoD2SE-Framework-MO2-v$version.zip"
    if (-not (Test-Path -LiteralPath $frameworkZip -PathType Leaf)) { throw "缺少框架发布包：$frameworkZip" }
    $frameworkStage = Join-Path $temp 'Framework'
    Expand-Archive -LiteralPath $frameworkZip -DestinationPath $frameworkStage -Force
    foreach ($name in 'SoD2SE.Loader.exe','SoD2SE.Core.dll','SoD2SE.GameApi.dll') {
        $file = Join-Path $frameworkStage $name
        if (-not (Test-Path -LiteralPath $file -PathType Leaf)) { throw "框架包缺少 $name：$frameworkZip" }
        Copy-Item -LiteralPath $file -Destination $game -Force
    }
    if (Test-Path -LiteralPath (Join-Path $frameworkStage 'meta.ini')) { throw "框架包不应包含 meta.ini：$frameworkZip" }
    Write-Output "已更新框架：$game"

    foreach ($entry in $entries) {
        $zip = Join-Path $packages $entry.Zip
        if (-not (Test-Path -LiteralPath $zip -PathType Leaf)) { throw "缺少发布包：$zip" }
        $extract = Join-Path $temp $entry.Directory
        Expand-Archive -LiteralPath $zip -DestinationPath $extract -Force
        $meta = Join-Path $extract 'meta.ini'
        $root = Join-Path $extract 'Root'
        if (-not (Test-Path -LiteralPath $meta -PathType Leaf) -or -not (Test-Path -LiteralPath $root -PathType Container)) { throw "包结构无效：$zip" }
        if (Test-Path -LiteralPath (Join-Path $extract 'Docs')) { throw "成品包不应包含 Docs：$zip" }
        $target = [IO.Path]::GetFullPath((Join-Path $mods $entry.Directory))
        if (-not $target.StartsWith($mods.TrimEnd('\') + '\', [StringComparison]::OrdinalIgnoreCase)) { throw "拒绝写入 MO2 mods 目录之外的路径：$target" }
        if (Test-Path -LiteralPath $target) { Remove-Item -LiteralPath $target -Recurse -Force }
        [IO.Directory]::CreateDirectory($target) | Out-Null
        Copy-Item -LiteralPath $meta -Destination $target
        Copy-Item -LiteralPath $root -Destination $target -Recurse
        $installed = (Select-String -Path (Join-Path $target 'meta.ini') -Pattern '^version=').Line
        Write-Output "已安装：$($entry.Directory)（$installed）"
    }

    foreach ($name in $legacy) {
        $stale = [IO.Path]::GetFullPath((Join-Path $mods $name))
        if ($stale.StartsWith($mods.TrimEnd('\') + '\', [StringComparison]::OrdinalIgnoreCase) -and (Test-Path -LiteralPath $stale)) {
            Remove-Item -LiteralPath $stale -Recurse -Force
            Write-Output "已清除旧版目录：$name"
        }
    }

    $profile = Join-Path (Join-Path $instance 'profiles') $ProfileName
    $modlist = Join-Path $profile 'modlist.txt'
    if (Test-Path -LiteralPath $modlist -PathType Leaf) {
        $lines = [Collections.Generic.List[string]]::new([IO.File]::ReadAllLines($modlist, [Text.Encoding]::UTF8))
        foreach ($name in $legacy) { $lines.Remove('-' + $name) | Out-Null; $lines.Remove('+' + $name) | Out-Null }
        foreach ($entry in $entries) {
            if (-not ($lines -contains ('+' + $entry.Directory)) -and -not ($lines -contains ('-' + $entry.Directory))) {
                $lines.Insert(0, '+' + $entry.Directory)
                Write-Output "已启用：$($entry.Directory)"
            }
        }
        [IO.File]::WriteAllLines($modlist, $lines, [Text.UTF8Encoding]::new($false))
    }
    Write-Output '完成。框架位于游戏根目录，由 MO2 管理五个插件包；用户配置与成长数据未被改动。'
}
finally {
    if (Test-Path -LiteralPath $temp) { Remove-Item -LiteralPath $temp -Recurse -Force }
}
