[CmdletBinding()]
param(
    [ValidateSet('build','check','test','package')][string]$Command = 'test',
    [string]$OutputDirectory = '',
    [string]$ProductRoot = '',
    [string]$NativeSettingsAsset = '',
    [string]$NativeUiReceipt = '',
    [string]$MainMenuAsset = '',
    [string]$SettingsHostAsset = '',
    [string]$Acceptance = '',
    [switch]$Candidate
)
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$framework = Split-Path -Parent $PSScriptRoot
if (-not $ProductRoot) { $ProductRoot = $framework }
$ProductRoot = [IO.Path]::GetFullPath($ProductRoot)
if (-not $OutputDirectory) { $OutputDirectory = Join-Path $ProductRoot '.work/rust' }
$OutputDirectory = [IO.Path]::GetFullPath($OutputDirectory)
$manifest = Join-Path $ProductRoot 'Cargo.toml'
if (-not (Test-Path -LiteralPath $manifest)) { throw "No Rust manifest: $manifest" }
$lock = Join-Path $ProductRoot 'rust-dependencies.lock.json'
if (Test-Path -LiteralPath $lock) {
    $pin = Get-Content -LiteralPath $lock -Raw | ConvertFrom-Json
    $revision = (& git -C $framework rev-parse HEAD).Trim()
    if ($LASTEXITCODE -ne 0 -or $revision -ne $pin.SoD2SE.revision) { throw 'Pinned Rust SDK revision mismatch.' }
}
$oldToolchain = $env:RUSTUP_TOOLCHAIN
$env:RUSTUP_TOOLCHAIN = '1.97.1'
try {
    $compiler = & rustc --version
    if ($LASTEXITCODE -ne 0 -or $compiler -notmatch '^rustc 1\.97\.1 ') { throw 'The locked Rust 1.97.1 toolchain is required.' }
    $action = if ($Command -eq 'package') { 'build' } else { $Command }
    $arguments = @($action, '--locked', '--offline', '--manifest-path', $manifest, '--target-dir', $OutputDirectory)
    if ($ProductRoot -eq $framework) { $arguments += '--workspace' }
    if ($Command -eq 'package') { $arguments += '--release' }
    & cargo @arguments
    if ($LASTEXITCODE -ne 0) { throw "Rust $Command failed." }
    if ($Command -eq 'test' -and $ProductRoot -eq $framework) {
        & cargo build --locked --offline --manifest-path $manifest --target-dir $OutputDirectory -p sod2se-example -p sod2se-loader -p sod2se-runtime
        if ($LASTEXITCODE -ne 0) { throw 'Rust ABI fixture build failed.' }
        $abi = Join-Path $OutputDirectory 'native-abi'
        & cmake -S (Join-Path $framework 'Tests/NativeAbi') -B $abi -A x64
        if ($LASTEXITCODE -ne 0) { throw 'C ABI fixture configuration failed.' }
        & cmake --build $abi --config Release
        if ($LASTEXITCODE -ne 0) { throw 'C ABI fixture compilation failed.' }
        & (Join-Path $abi 'Release/NativeAbiTest.exe') (Join-Path $OutputDirectory 'debug/sod2se_example.dll') (Join-Path $OutputDirectory 'debug/sod2se_runtime.dll')
        if ($LASTEXITCODE -ne 0) { throw 'Independent C ABI fixture failed.' }
        & (Join-Path $OutputDirectory 'debug/sod2se-loader.exe') --self-test
        if ($LASTEXITCODE -ne 0) { throw 'Native loader self-test failed.' }
    }
    if ($Command -eq 'package') {
        $argsList = @('-B', (Join-Path $framework 'Automation/Package/package_rust.py'), '--product-root', $ProductRoot, '--build-root', $OutputDirectory)
        if ($Candidate) { $argsList += '--candidate' }
        if ($NativeSettingsAsset) { $argsList += @('--native-settings-asset', $NativeSettingsAsset) }
        if ($NativeUiReceipt) { $argsList += @('--native-ui-receipt', $NativeUiReceipt) }
        if ($MainMenuAsset) { $argsList += @('--main-menu-asset', $MainMenuAsset) }
        if ($SettingsHostAsset) { $argsList += @('--settings-host-asset', $SettingsHostAsset) }
        if ($Acceptance) { $argsList += @('--acceptance', $Acceptance) }
        & python @argsList
        if ($LASTEXITCODE -ne 0) { throw 'Rust package failed or release gate refused.' }
    }
} finally { $env:RUSTUP_TOOLCHAIN = $oldToolchain }
