[CmdletBinding()]
param(
    [string]$MoRoot = 'E:\Game\SD2_mod',
    [string]$GameRoot = 'E:\SteamLibrary\steamapps\common\StateOfDecay2',
    [string]$ProfileName = 'Default',
    [string]$BuildDirectory = ''
)
$projectRoot = (Split-Path -Parent (Split-Path -Parent $PSScriptRoot))


Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

if ([string]::IsNullOrWhiteSpace($BuildDirectory)) { throw 'BuildDirectory must point to the validated 0.6.3 build.' }
$mo = [IO.Path]::GetFullPath((Resolve-Path -LiteralPath $MoRoot).ProviderPath)
$game = [IO.Path]::GetFullPath((Resolve-Path -LiteralPath $GameRoot).ProviderPath)
$build = [IO.Path]::GetFullPath((Resolve-Path -LiteralPath $BuildDirectory).ProviderPath)
$mods = [IO.Path]::GetFullPath((Join-Path $mo 'mods'))
$downloads = [IO.Path]::GetFullPath((Join-Path $mo 'downloads'))
$backupRoot = [IO.Path]::GetFullPath((Join-Path $mo 'sod2-support\manual-install-backups'))
$backup = Join-Path $backupRoot ('mcm-language-autodetect-' + (Get-Date -Format 'yyyyMMdd-HHmmss') + '-' + [Guid]::NewGuid().ToString('N').Substring(0, 8))
$staging = Join-Path ([IO.Path]::GetTempPath()) ('SoD2SE-McmLanguageInstall-' + [Guid]::NewGuid().ToString('N'))
$entries = @(
    @{ Zip = 'SoD2SE-Mcm-MO2-v0.6.3-preview-native-settings.zip'; Directory = '模组配置菜单 - Mod Configuration Menu'; Id = 'Mcm' },
    @{ Zip = 'SoD2-NativeModSettingsEntry-MO2-v0.2.9-preview.zip'; Directory = '原版 Mod 设置入口 - Native Mod Settings Entry'; Id = 'NativeModSettingsEntry' }
)
$coreSource = Join-Path $build 'SoD2SE.Core.dll'
$coreTarget = Join-Path $game 'SoD2SE.Core.dll'
$profileFile = Join-Path (Join-Path $mo 'profiles') (Join-Path $ProfileName 'modlist.txt')
$profileHash = if (Test-Path -LiteralPath $profileFile -PathType Leaf) { (Get-FileHash -LiteralPath $profileFile -Algorithm SHA256).Hash } else { $null }
$coreBackedUp = $false
$modsBackedUp = [Collections.Generic.List[string]]::new()
$installStarted = $false

function Assert-InDirectory([string]$root, [string]$path) {
    $resolvedRoot = [IO.Path]::GetFullPath($root).TrimEnd('\') + '\'
    $resolvedPath = [IO.Path]::GetFullPath($path)
    if (-not $resolvedPath.StartsWith($resolvedRoot, [StringComparison]::OrdinalIgnoreCase)) {
        throw "拒绝操作目标目录之外的路径：$resolvedPath"
    }
}

function Copy-ModBackup([string]$source, [string]$destination) {
    if (-not (Test-Path -LiteralPath $source -PathType Container)) { throw "MO2 Mod folder is missing: $source" }
    Copy-Item -LiteralPath $source -Destination $destination -Recurse
}

try {
    if (Get-Process StateOfDecay2*,SoD2SE.Loader -ErrorAction SilentlyContinue) {
        throw '请先完全退出游戏与 SoD2SE 加载器；游戏正在使用的文件不会被替换。'
    }
    foreach ($path in @($mods, $downloads, $coreSource, $coreTarget)) {
        if (-not (Test-Path -LiteralPath $path)) { throw "Required install path is missing: $path" }
    }
    [IO.Directory]::CreateDirectory($staging) | Out-Null
    foreach ($entry in $entries) {
        $zip = Join-Path $downloads $entry.Zip
        if (-not (Test-Path -LiteralPath $zip -PathType Leaf)) { throw "MO2 package is missing: $zip" }
        $unpack = Join-Path $staging $entry.Id
        Expand-Archive -LiteralPath $zip -DestinationPath $unpack
        if (-not (Test-Path -LiteralPath (Join-Path $unpack 'meta.ini') -PathType Leaf) -or
            -not (Test-Path -LiteralPath (Join-Path $unpack $(if ($entry.Id -eq 'Mcm') { 'Root' } else { 'Saved' })) -PathType Container) -or
            (Test-Path -LiteralPath (Join-Path $unpack 'Docs'))) {
            throw "MO2 package layout is invalid: $zip"
        }
    }

    $mcmStage = Join-Path (Join-Path $staging 'Mcm') 'Root\Plugins'
    $entryStage = Join-Path (Join-Path $staging 'NativeModSettingsEntry') 'Saved\Cooked\WindowsNoEditor\StateOfDecay2\Content\Art\UI\settings.uasset'
    foreach ($file in @(
        (Join-Path $mcmStage 'Mcm.dll'),
        (Join-Path $mcmStage 'Mcm\SoD2SE.Mcm.Native.dll'),
        $entryStage
    )) {
        if (-not (Test-Path -LiteralPath $file -PathType Leaf)) { throw "Package payload is missing: $file" }
    }

    [IO.Directory]::CreateDirectory($backupRoot) | Out-Null
    [IO.Directory]::CreateDirectory($backup) | Out-Null
    Copy-Item -LiteralPath $coreTarget -Destination (Join-Path $backup 'SoD2SE.Core.dll.before')
    $coreBackedUp = $true
    foreach ($entry in $entries) {
        $target = [IO.Path]::GetFullPath((Join-Path $mods $entry.Directory))
        Assert-InDirectory $mods $target
        Copy-ModBackup $target (Join-Path $backup $entry.Directory)
        $modsBackedUp.Add($entry.Directory)
        $oldPackageName = if ($entry.Id -eq 'Mcm') { 'SoD2SE-Mcm-MO2-v0.6.2-preview-native-settings.zip' } else { 'SoD2-NativeModSettingsEntry-MO2-v0.2.4-preview.zip' }
        $oldPackage = Join-Path $downloads $oldPackageName
        if (Test-Path -LiteralPath $oldPackage -PathType Leaf) { Copy-Item -LiteralPath $oldPackage -Destination (Join-Path $backup ([IO.Path]::GetFileName($oldPackage))) }
        $oldMeta = $oldPackage + '.meta'
        if (Test-Path -LiteralPath $oldMeta -PathType Leaf) { Copy-Item -LiteralPath $oldMeta -Destination (Join-Path $backup ([IO.Path]::GetFileName($oldMeta))) }
    }

    $installStarted = $true
    foreach ($entry in $entries) {
        $target = [IO.Path]::GetFullPath((Join-Path $mods $entry.Directory))
        Assert-InDirectory $mods $target
        Remove-Item -LiteralPath $target -Recurse -Force
        [IO.Directory]::CreateDirectory($target) | Out-Null
        Copy-Item -LiteralPath (Join-Path (Join-Path $staging $entry.Id) 'meta.ini') -Destination $target
        $payloadRoot = Join-Path (Join-Path $staging $entry.Id) 'Root'
        if ($entry.Id -eq 'NativeModSettingsEntry') {
            Copy-Item -LiteralPath (Join-Path (Join-Path $staging $entry.Id) 'Saved') -Destination $target -Recurse
        }
        else {
            Copy-Item -LiteralPath $payloadRoot -Destination $target -Recurse
        }
    }
    Copy-Item -LiteralPath $coreSource -Destination $coreTarget -Force

    $installedMcm = Join-Path $mods '模组配置菜单 - Mod Configuration Menu\Root\Plugins'
    $installedEntry = Join-Path $mods '原版 Mod 设置入口 - Native Mod Settings Entry\Saved\Cooked\WindowsNoEditor\StateOfDecay2\Content\Art\UI\settings.uasset'
    $wrongEntry = Join-Path $mods '原版 Mod 设置入口 - Native Mod Settings Entry\Root\Saved\Cooked\WindowsNoEditor\StateOfDecay2\Content\Art\UI\settings.uasset'
    if (Test-Path -LiteralPath $wrongEntry -PathType Leaf) {
        throw "Native settings asset was installed under an extra Root directory: $wrongEntry"
    }
    foreach ($pair in @(
        @{ Actual = Join-Path $installedMcm 'Mcm.dll'; Expected = Join-Path $build 'Plugins\Mcm.dll' },
        @{ Actual = Join-Path $installedMcm 'Mcm\SoD2SE.Mcm.Native.dll'; Expected = Join-Path $build 'Plugins\Mcm\SoD2SE.Mcm.Native.dll' },
        @{ Actual = $installedEntry; Expected = $entryStage },
        @{ Actual = $coreTarget; Expected = $coreSource }
    )) {
        $actualHash = (Get-FileHash -LiteralPath $pair.Actual -Algorithm SHA256).Hash
        $expectedHash = (Get-FileHash -LiteralPath $pair.Expected -Algorithm SHA256).Hash
        if ($actualHash -ne $expectedHash) { throw "Installed file hash mismatch: $($pair.Actual)" }
    }
    foreach ($entry in $entries) {
        $meta = Get-Content -LiteralPath (Join-Path (Join-Path $mods $entry.Directory) 'meta.ini') -Raw
        $expectedVersion = if ($entry.Id -eq 'Mcm') { '0.6.3.0-preview' } else { '0.2.9.0-preview' }
        if (-not $meta.Contains("version=$expectedVersion") -or -not $meta.Contains("name=$($entry.Directory)")) {
            throw "Installed MO2 metadata mismatch: $($entry.Directory)"
        }
    }
    if ($profileHash -and (Get-FileHash -LiteralPath $profileFile -Algorithm SHA256).Hash -ne $profileHash) {
        throw 'MO2 profile state changed unexpectedly.'
    }

    foreach ($oldName in @('SoD2SE-Mcm-MO2-v0.6.2-preview-native-settings.zip', 'SoD2-NativeModSettingsEntry-MO2-v0.2.4-preview.zip')) {
        foreach ($suffix in @('', '.meta')) {
            $oldFile = Join-Path $downloads ($oldName + $suffix)
            if (Test-Path -LiteralPath $oldFile -PathType Leaf) {
                Remove-Item -LiteralPath $oldFile -Force
            }
        }
    }
    Write-Output "Installed MCM 0.6.3-preview, native settings entry 0.2.9-preview, and the matching Core ABI 0.6.0 build."
    Write-Output "Backup: $backup"
    Write-Output "MO2 profile enable state preserved: $ProfileName"
}
catch {
    if ($installStarted) {
        foreach ($directory in $modsBackedUp) {
            $target = [IO.Path]::GetFullPath((Join-Path $mods $directory))
            Assert-InDirectory $mods $target
            if (Test-Path -LiteralPath $target) { Remove-Item -LiteralPath $target -Recurse -Force }
            Copy-Item -LiteralPath (Join-Path $backup $directory) -Destination $target -Recurse
        }
        if ($coreBackedUp -and (Test-Path -LiteralPath (Join-Path $backup 'SoD2SE.Core.dll.before'))) {
            Copy-Item -LiteralPath (Join-Path $backup 'SoD2SE.Core.dll.before') -Destination $coreTarget -Force
        }
        foreach ($oldName in @('SoD2SE-Mcm-MO2-v0.6.2-preview-native-settings.zip', 'SoD2-NativeModSettingsEntry-MO2-v0.2.4-preview.zip')) {
            foreach ($suffix in @('', '.meta')) {
                $fileName = $oldName + $suffix
                $saved = Join-Path $backup $fileName
                $download = Join-Path $downloads $fileName
                if ((Test-Path -LiteralPath $saved -PathType Leaf) -and -not (Test-Path -LiteralPath $download)) {
                    Copy-Item -LiteralPath $saved -Destination $download
                }
            }
        }
    }
    throw
}
finally {
    if (Test-Path -LiteralPath $staging) {
        $tempBoundary = [IO.Path]::GetFullPath([IO.Path]::GetTempPath()).TrimEnd('\') + '\'
        if (-not [IO.Path]::GetFullPath($staging).StartsWith($tempBoundary, [StringComparison]::OrdinalIgnoreCase)) {
            throw "Refusing to clean staging outside Temp: $staging"
        }
        Remove-Item -LiteralPath $staging -Recurse -Force
    }
}
