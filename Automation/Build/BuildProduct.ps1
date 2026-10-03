[CmdletBinding()]
param(
    [Parameter(Mandatory=$true)][ValidateSet('build','check','test','package')][string]$Command,
    [Parameter(Mandatory=$true)][string]$ProductRoot,
    [string]$Sod2seRoot = '',
    [string]$OutputDirectory = '',
    [string]$NativeSettingsAsset = ''
)
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$ProductRoot = [IO.Path]::GetFullPath($ProductRoot)
if ([string]::IsNullOrWhiteSpace($Sod2seRoot)) { $Sod2seRoot = $env:SOD2SE_ROOT }
if ([string]::IsNullOrWhiteSpace($Sod2seRoot)) {
    $parent = Split-Path -Parent $ProductRoot
    $candidates = @(
        (Join-Path $parent 'SoD2SE'),
        (Join-Path (Split-Path -Parent $parent) 'Projects/SoD2SE'))
    foreach ($candidate in $candidates) {
        if (Test-Path -LiteralPath (Join-Path $candidate 'Automation/Build/build.ps1')) { $Sod2seRoot = $candidate; break }
    }
}
if ([string]::IsNullOrWhiteSpace($Sod2seRoot)) {
    throw 'Provide -Sod2seRoot. Restore the pinned SoD2SE source dependency before building this product.'
}
$Sod2seRoot = [IO.Path]::GetFullPath($Sod2seRoot)
$lockPath = Join-Path $ProductRoot 'dependencies.lock.json'
if (Test-Path -LiteralPath $lockPath -PathType Leaf) {
    $lock = Get-Content -LiteralPath $lockPath -Raw -Encoding UTF8 | ConvertFrom-Json
    $expected = [string]$lock.dependencies.SoD2SE.revision
    $actual = (& git -C $Sod2seRoot rev-parse HEAD).Trim()
    if ($LASTEXITCODE -ne 0 -or $actual -ne $expected) {
        throw "SoD2SE dependency revision mismatch: expected $expected, got $actual"
    }
}
if ([string]::IsNullOrWhiteSpace($OutputDirectory)) {
    $workspace = Split-Path -Parent (Split-Path -Parent $ProductRoot)
    if (Test-Path -LiteralPath (Join-Path $workspace 'workspace.toml')) {
        $OutputDirectory = Join-Path $workspace ('.work/products/' + (Split-Path -Leaf $ProductRoot))
    } else {
        $OutputDirectory = Join-Path $ProductRoot '.work/build'
    }
}
$output = $ExecutionContext.SessionState.Path.GetUnresolvedProviderPathFromPSPath($OutputDirectory)
$manifestPath = Join-Path $ProductRoot 'src/mod.json'
$manifest = $null
if (Test-Path -LiteralPath $manifestPath -PathType Leaf) {
    $manifest = Get-Content -LiteralPath $manifestPath -Raw -Encoding UTF8 | ConvertFrom-Json
    if ($manifest.schema -ne 1 -or -not $manifest.id) { throw "Invalid product manifest: $manifestPath" }
    foreach ($file in $manifest.files) {
        if ($file.input -like 'source:*') {
            $relative = $file.input.Substring(7).Replace('/', [IO.Path]::DirectorySeparatorChar)
            $candidate = [IO.Path]::GetFullPath((Join-Path $ProductRoot $relative))
            if (-not $candidate.StartsWith($ProductRoot.TrimEnd('\') + '\', [StringComparison]::OrdinalIgnoreCase)) {
                throw "Source payload escapes product root: $($file.input)"
            }
        }
    }
}
function Invoke-ProductBuild {
    if (-not $manifest) { Write-Output 'PASS: this resource product has no compilation step.'; return }
    if ($manifest.id -eq 'NativeModSettingsEntry') {
        Write-Output 'SKIPPED: resource generation needs a hash-matched local asset input and the ReverseEngineering tool entrypoint.'
        return
    }
    if ($manifest.id -eq 'SkipStartupIntro') {
        $python = (Get-Command python -ErrorAction Stop).Source
        $packager = Join-Path $Sod2seRoot 'Automation/Package/package_product.py'
        $checkArgs = @($packager, '--product-root', $ProductRoot, '--build-root', $output,
            '--output-dir', (Join-Path $output 'packages'), '--validate-only')
        & $python -B @checkArgs
        if ($LASTEXITCODE -ne 0) { throw "Product source check failed ($LASTEXITCODE)." }
        return
    }
    $script = Join-Path $Sod2seRoot 'Automation/Build/build.ps1'
    if (-not (Test-Path -LiteralPath $script -PathType Leaf)) { throw "Missing SoD2SE build engine: $script" }
    $ids = [string]$manifest.id
    $pluginSource = Join-Path $ProductRoot 'src'
    $nativeSource = Join-Path $ProductRoot 'native'
    $buildParams = @{
        OutputDirectory = $output
        Ids = @($ids)
        NoLoader = $true
        PluginSourceDirectory = $pluginSource
        PluginId = $ids
        Sod2seRoot = $Sod2seRoot
    }
    if (Test-Path -LiteralPath $nativeSource -PathType Container) { $buildParams.NativeSourceDirectory = $nativeSource }
    $oldRoot = $env:SOD2SE_ROOT
    $env:SOD2SE_ROOT = $Sod2seRoot
    try { & $script @buildParams; if ($LASTEXITCODE -ne 0) { throw "Product build failed ($LASTEXITCODE)." } }
    finally { $env:SOD2SE_ROOT = $oldRoot }
}
function Invoke-ProductPackage {
    if (-not $manifest) { throw "Missing product manifest: $manifestPath" }
    if (-not $manifest.publish) { throw 'This prototype is not eligible for release packaging.' }
    if ($manifest.id -eq 'NativeModSettingsEntry' -and -not $NativeSettingsAsset) {
        Write-Output 'SKIPPED: NativeModSettingsEntry requires a hash-matched, local native settings asset.'
        return
    }
    if ($manifest.id -ne 'NativeModSettingsEntry') { Invoke-ProductBuild }
    $python = (Get-Command python -ErrorAction Stop).Source
    $packager = Join-Path $Sod2seRoot 'Automation/Package/package_product.py'
    if (-not (Test-Path -LiteralPath $packager -PathType Leaf)) { throw "Missing shared package implementation: $packager" }
    $packageArgs = @($packager, '--product-root', $ProductRoot, '--build-root', $output,
        '--output-dir', (Join-Path $output 'packages'))
    if ($NativeSettingsAsset) { $packageArgs += @('--native-settings-asset', $NativeSettingsAsset) }
    & $python -B @packageArgs
    if ($LASTEXITCODE -ne 0) { throw "Product packaging failed ($LASTEXITCODE)." }
}
switch ($Command) {
    'check' {
        if ($manifest) {
            if ($manifest.id -eq 'NativeModSettingsEntry' -and -not $NativeSettingsAsset) {
                Write-Output 'SKIPPED: fixed-build asset input is not attached.'
            } else {
                $python = (Get-Command python -ErrorAction Stop).Source
                $packager = Join-Path $Sod2seRoot 'Automation/Package/package_product.py'
                $checkArgs = @($packager, '--product-root', $ProductRoot, '--build-root', $output,
                    '--output-dir', (Join-Path $output 'packages'), '--validate-only')
                if ($NativeSettingsAsset) { $checkArgs += @('--native-settings-asset', $NativeSettingsAsset) }
                & $python -B @checkArgs
                if ($LASTEXITCODE -ne 0) { throw "Product check failed ($LASTEXITCODE)." }
            }
        }
        elseif ($ProductRoot -match 'NativeModSettingsEntry') { Write-Output 'SKIPPED: fixed-build input is required for resource validation.' }
        else { Write-Output 'PASS: resource-only product.' }
    }
    'build' { Invoke-ProductBuild }
    'package' { Invoke-ProductPackage }
    'test' {
        if ($manifest -and $manifest.id -eq 'NativeModSettingsEntry') {
            Write-Output 'SKIPPED: offline native asset input is not attached.'
        } else {
            Invoke-ProductBuild
            $managedTests = @()
            if ($manifest -and $manifest.id -eq 'Mcm') { $managedTests = @('McmSmoke.cs') }
            if ($manifest -and $manifest.id -eq 'Roguelite') { $managedTests = @('RogueliteSmoke.cs') }
            $productTestExecuted = $manifest -and $manifest.id -eq 'SkipStartupIntro'
            if ($manifest -and $manifest.id -eq 'Roguelite') {
                $nativeCache = Join-Path $output 'native-build'
                & cmake --build $nativeCache --config Release --target GrowthUiTest GrowthHostWireTest --parallel
                if ($LASTEXITCODE -ne 0) { throw "Roguelite managed/native host fixtures failed to build ($LASTEXITCODE)." }
                $testDirectory = Join-Path $output '.tests'
                [IO.Directory]::CreateDirectory($testDirectory) | Out-Null
                Copy-Item -LiteralPath (Join-Path $nativeCache 'Release/GrowthUiTest.exe') -Destination $testDirectory -Force
            }
            if ($managedTests.Count -gt 0) {
                $compilerCandidates = @(
                    (Join-Path $env:WINDIR 'Microsoft.NET/Framework64/v4.0.30319/csc.exe'),
                    (Join-Path $env:WINDIR 'Microsoft.NET/Framework/v4.0.30319/csc.exe'))
                $compiler = $compilerCandidates | Where-Object { Test-Path -LiteralPath $_ -PathType Leaf } | Select-Object -First 1
                if (-not $compiler) { throw 'No .NET Framework C# compiler is installed.' }
                foreach ($testName in $managedTests) {
                    $testSource = Join-Path $ProductRoot (Join-Path 'tests/managed' $testName)
                    if (-not (Test-Path -LiteralPath $testSource -PathType Leaf)) { throw "Missing managed test source: $testSource" }
                    $testSources = @($testSource)
                    $entryPoint = ''
                    if ($manifest.id -eq 'Roguelite') {
                        $testSources += @((Join-Path $ProductRoot 'tests/managed/GrowthAdapterSmoke.cs'),
                            (Join-Path $ProductRoot 'tests/managed/GrowthPageSmoke.cs'))
                        $entryPoint = '/main:RogueliteSmoke'
                    }
                    $testDirectory = Join-Path $output '.tests'
                    $testExe = Join-Path $testDirectory ([IO.Path]::GetFileNameWithoutExtension($testName) + '.exe')
                    [IO.Directory]::CreateDirectory($testDirectory) | Out-Null
                    foreach ($dependency in @('SoD2SE.Core.dll','SoD2SE.GameApi.dll',
                            (Join-Path 'Plugins' ($manifest.id + '.dll')))) {
                        Copy-Item -LiteralPath (Join-Path $output $dependency) -Destination $testDirectory -Force
                    }
                    $compilerArgs = @(
                        '/nologo', '/platform:x64', '/codepage:65001', '/warnaserror+',
                        '/reference:System.dll', '/reference:System.Core.dll', '/reference:System.Numerics.dll',
                        ("/reference:" + (Join-Path $output 'SoD2SE.Core.dll')),
                        ("/reference:" + (Join-Path $output 'SoD2SE.GameApi.dll')),
                        ("/reference:" + (Join-Path $output (Join-Path 'Plugins' ($manifest.id + '.dll')))),
                        ("/out:" + $testExe))
                    if ($entryPoint) { $compilerArgs += $entryPoint }
                    $compilerArgs += $testSources
                    & $compiler @compilerArgs
                    if ($LASTEXITCODE -ne 0) { throw "Managed test compile failed: $testName ($LASTEXITCODE)." }
                    Push-Location $output
                    try { & $testExe; if ($LASTEXITCODE -ne 0) { throw "Managed test failed: $testName ($LASTEXITCODE)." } }
                    finally { Pop-Location }
                }
                $productTestExecuted = $true
            }
            if ($manifest -and $manifest.id -eq 'Roguelite') {
                $compilerCandidates = @(
                    (Join-Path $env:WINDIR 'Microsoft.NET/Framework64/v4.0.30319/csc.exe'),
                    (Join-Path $env:WINDIR 'Microsoft.NET/Framework/v4.0.30319/csc.exe'))
                $compiler = $compilerCandidates | Where-Object { Test-Path -LiteralPath $_ -PathType Leaf } | Select-Object -First 1
                if (-not $compiler) { throw 'No .NET Framework C# compiler is installed.' }
                $transportSource = Join-Path $ProductRoot 'tests/managed/GrowthNativeTransportSmoke.cs'
                $transportExe = Join-Path $output '.tests/GrowthNativeTransportSmoke.exe'
                $transportArgs = @('/nologo','/platform:x64','/codepage:65001','/warnaserror+',
                    '/reference:System.dll','/reference:System.Core.dll',
                    ("/reference:" + (Join-Path $output '.tests/SoD2SE.Core.dll')),
                    ("/out:" + $transportExe),$transportSource)
                & $compiler @transportArgs
                if ($LASTEXITCODE -ne 0) { throw "Growth native transport test compile failed ($LASTEXITCODE)." }
                $wireFixture = Join-Path $output 'native-build/Release/GrowthHostWireTest.exe'
                $growthNative = Join-Path $output 'Plugins/Roguelite/SoD2SE.Growth.Native.dll'
                Push-Location (Join-Path $output '.tests')
                try {
                    & $transportExe $wireFixture $growthNative
                    if ($LASTEXITCODE -ne 0) { throw "Growth native transport test failed ($LASTEXITCODE)." }
                }
                finally { Pop-Location }
            }
            $nativeTests = @{}
            $nativeTests['Mcm'] = @('NativeSettingsTest','NativeSettingsIggyTest')
            $nativeTests['MeleeSpeed'] = @('MeleeNativeTest')
            $nativeTests['Roguelite'] = @('GrowthAbilityClocksTest','GrowthActorPoliciesTest','GrowthActorSourceTest',
                'GrowthCampaignSourceTest','GrowthConsumerTest','GrowthFrameTest','GrowthHostTest',
                'GrowthKillTest','GrowthKnockdownTest','GrowthLoadingScreenTest','GrowthMovementTest',
                'GrowthObjectTest','GrowthPlayReadinessTest','GrowthRangedBindingTest','GrowthRangedTest',
                'GrowthStatTest','GrowthUiTest','GrowthVitalsTest','GrowthWorldTest')
            if ($manifest -and $nativeTests.ContainsKey([string]$manifest.id) -and $nativeTests[[string]$manifest.id].Count -gt 0) {
                $cache = Join-Path $output 'native-build'
                & cmake --build $cache --config Release --target @($nativeTests[[string]$manifest.id]) --parallel
                if ($LASTEXITCODE -ne 0) { throw "Native test build failed ($LASTEXITCODE)." }
                foreach ($name in $nativeTests[[string]$manifest.id]) {
                    $exe = Join-Path $cache ('Release/' + $name + '.exe')
                    & $exe
                    if ($LASTEXITCODE -ne 0) { throw "Native test failed: $name ($LASTEXITCODE)." }
                }
                $productTestExecuted = $true
            }
            if ($productTestExecuted) {
                Write-Output 'PASS: product offline build and available product checks completed.'
            } else {
                Write-Output 'SKIPPED: build passed, but this product has no existing product-specific offline test fixture.'
            }
        }
    }
}
