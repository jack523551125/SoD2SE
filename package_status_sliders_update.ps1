[CmdletBinding()]
param(
    [Parameter(Mandatory=$true)][string]$SettingsAsset,
    [string]$GameRoot = 'E:\SteamLibrary\steamapps\common\StateOfDecay2',
    [string]$OutputDirectory = (Join-Path $PSScriptRoot '..\..\outputs\MenuAndIntroUpdate-20260928')
)
Set-StrictMode -Version Latest
$ErrorActionPreference='Stop'
$out=[IO.Path]::GetFullPath($OutputDirectory)
if (Test-Path -LiteralPath $out) { throw 'Use a fresh output directory.' }
$build=Join-Path $out 'Build'
[IO.Directory]::CreateDirectory($build) | Out-Null
foreach($file in @('SoD2SE.Core.dll','SoD2SE.GameApi.dll')) {
    Copy-Item -LiteralPath (Join-Path $GameRoot $file) -Destination $build
}
$version=Join-Path $build 'AssemblyVersion.cs'
[IO.File]::WriteAllText($version, '[assembly:System.Reflection.AssemblyVersion("0.6.1.0")]
[assembly:System.Reflection.AssemblyFileVersion("0.6.1.0")]
[assembly:System.Reflection.AssemblyInformationalVersion("0.6.1-preview")]', [Text.UTF8Encoding]::new($true))
$csc=Join-Path $env:WINDIR 'Microsoft.NET\Framework64\v4.0.30319\csc.exe'
$common=@('/nologo','/platform:x64','/highentropyva+','/codepage:65001','/optimize+','/debug-','/warn:4','/warnaserror+',
    '/reference:System.dll','/reference:System.Core.dll','/reference:System.Numerics.dll','/reference:System.Drawing.dll','/reference:System.Windows.Forms.dll',
    "/reference:$build\SoD2SE.Core.dll","/reference:$build\SoD2SE.GameApi.dll")
foreach($id in @('UnlimitedFollowers','UnlimitedCommunity','MeleeSpeed')) {
    $sources=@(Get-ChildItem -LiteralPath (Join-Path $PSScriptRoot "Plugins\$id") -Filter '*.cs' -File | ForEach-Object FullName)
    & $csc @common /target:library "/out:$build\$id.dll" @sources $version
    if($LASTEXITCODE -ne 0) { throw "Compile failed: $id" }
}
foreach($test in @('MeleeConfigSmoke','StatusPagesSmoke')) {
    & $csc @common /target:exe "/out:$build\$test.exe" "/reference:$build\MeleeSpeed.dll" "/reference:$build\UnlimitedFollowers.dll" "/reference:$build\UnlimitedCommunity.dll" (Join-Path $PSScriptRoot "Tests\$test.cs")
    if($LASTEXITCODE -ne 0) { throw "Test compile failed: $test" }
    & "$build\$test.exe"
    if($LASTEXITCODE -ne 0) { throw "Test failed: $test" }
}
function Package([string]$id,[string]$name,[string]$release,[hashtable]$files) {
    $stage=Join-Path $out "Packages\$name"
    [IO.Directory]::CreateDirectory($stage) | Out-Null
    foreach($relative in $files.Keys) {
        $dest=Join-Path $stage $relative
        [IO.Directory]::CreateDirectory((Split-Path -Parent $dest)) | Out-Null
        Copy-Item -LiteralPath $files[$relative] -Destination $dest
    }
    $archive="SoD2-$id-MO2-v$release.zip"
    [IO.File]::WriteAllLines((Join-Path $stage 'meta.ini'), @('[General]','gameName=State of Decay 2','modID=0',
        "name=$name","version=$release","newestVersion=$release","installationFile=$archive","soD2seId=$id",'category=SoD2SE'),[Text.UTF8Encoding]::new($false))
    Compress-Archive -Path (Join-Path $stage '*') -DestinationPath (Join-Path $out $archive)
    Write-Output "PACKAGED $archive"
}
Package 'UnlimitedFollowers' '无限随从 - Unlimited Followers' '0.6.1-preview' @{'Root\Plugins\UnlimitedFollowers.dll'="$build\UnlimitedFollowers.dll"}
Package 'UnlimitedCommunity' '社区招募无上限 - Unlimited Community Recruitment' '0.6.1-preview' @{'Root\Plugins\UnlimitedCommunity.dll'="$build\UnlimitedCommunity.dll"}
# The already installed provider is retained byte-for-byte; this update only changes MCM registration.
$meleeNative='E:\Game\SD2_mod\mods\近战攻速 - Melee Attack Speed\Root\Plugins\MeleeSpeed\SoD2SE.MeleeSpeed.Native.dll'
Package 'MeleeSpeed' '近战攻速 - Melee Attack Speed' '0.6.1-preview' @{
    'Root\Plugins\MeleeSpeed.dll'="$build\MeleeSpeed.dll";'Root\Plugins\MeleeSpeed\SoD2SE.MeleeSpeed.Native.dll'=$meleeNative}
Package 'NativeModSettingsEntry' '原版 Mod 设置入口 - Native Mod Settings Entry' '0.3.1-preview' @{
    'Saved\Cooked\WindowsNoEditor\StateOfDecay2\Content\Art\UI\settings.uasset'=$SettingsAsset}
Package 'SkipStartupIntro' '跳过启动介绍 - Skip Startup Intro' '0.1.1-preview' @{
    'Root\StateOfDecay2\Content\Movies\Logos.bk2'=(Join-Path $PSScriptRoot 'Mods\SkipStartupIntro\Root\StateOfDecay2\Content\Movies\Logos.bk2')}
