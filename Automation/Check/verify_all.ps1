[CmdletBinding()]
param(
    [string]$GameExePath = '',
    [string]$PackageDirectory = '',
    [string]$ZipPath = ''
)
$projectRoot = (Split-Path -Parent (Split-Path -Parent $PSScriptRoot))


Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

# Shared lookups: the framework version comes from Core/SoD2SE.Core.cs, and the
# game executable is discovered instead of being pinned to one machine.
$environmentScript = Join-Path $projectRoot 'Automation/Environment.ps1'
if (-not (Test-Path -LiteralPath $environmentScript -PathType Leaf)) { throw "找不到共享脚本：$environmentScript" }
. $environmentScript

function Invoke-Checked {
    param(
        [Parameter(Mandatory = $true)][string]$Label,
        [Parameter(Mandatory = $true)][scriptblock]$Command
    )

    & $Command
    if ($LASTEXITCODE -ne 0) {
        throw "$Label 失败，退出码：$LASTEXITCODE"
    }
    Write-Host "PASS: $Label"
}

function Invoke-PythonChecked {
    param(
        [Parameter(Mandatory = $true)][string]$Label,
        [Parameter(Mandatory = $true)][string]$ScriptPath,
        [string[]]$Arguments = @()
    )

    Invoke-Checked -Label $Label -Command {
        & python $ScriptPath @Arguments
    }.GetNewClosure()
}

function Invoke-ResearchToolTests {
    param([Parameter(Mandatory = $true)][string]$ResearchDirectory)

    $toolDirectory = Join-Path $ResearchDirectory 'tests'
    Invoke-Checked -Label '静态逆向工具单元测试' -Command {
        & python -m unittest discover -s $toolDirectory -p 'test_*.py' -v
    }.GetNewClosure()
}

function Invoke-LoaderChecked {
    param(
        [Parameter(Mandatory = $true)][string]$Label,
        [Parameter(Mandatory = $true)][string]$Path,
        [string[]]$Arguments = @()
    )

    # The loader is a Windows GUI executable so MO2 does not create a console
    # window. PowerShell's call operator does not reliably populate
    # LASTEXITCODE for GUI executables; Start-Process gives us the real exit code.
    $process = Start-Process -FilePath $Path -ArgumentList $Arguments -WindowStyle Hidden -Wait -PassThru
    if ($process.ExitCode -ne 0) {
        throw "$Label 失败，退出码：$($process.ExitCode)"
    }
    Write-Host "PASS: $Label"
}

$scriptRoot = $ExecutionContext.SessionState.Path.GetUnresolvedProviderPathFromPSPath($projectRoot)
$sourceRoot = $scriptRoot
$packageOnly = $false
if (-not (Test-Path -LiteralPath (Join-Path $sourceRoot 'Core\SoD2SE.Core.cs') -PathType Leaf)) {
    $sourceRoot = Join-Path $scriptRoot 'source'
    $packageOnly = $true
}
if (-not (Test-Path -LiteralPath (Join-Path $sourceRoot 'Core\SoD2SE.Core.cs') -PathType Leaf)) {
    throw "找不到 SoD2SE 源码目录：$sourceRoot"
}

# Output names follow the one version literal, so a release never lands in a
# directory named after an older build.
$frameworkVersion = Get-SoD2SEVersion -SourceRoot $sourceRoot
if ([string]::IsNullOrWhiteSpace($PackageDirectory) -and -not $packageOnly) {
    $PackageDirectory = Join-Path $scriptRoot "..\..\dist\SoD2SE-CommunityMods-v$frameworkVersion"
}
if ([string]::IsNullOrWhiteSpace($ZipPath) -and -not $packageOnly) {
    $ZipPath = Join-Path $scriptRoot "..\..\dist\SoD2SE-CommunityMods-v$frameworkVersion.zip"
}

$resolvedGameExe = Resolve-SoD2GameExecutable -GameExePath $GameExePath -HintFileDirectory $projectRoot

if ($packageOnly) {
    $packageRoot = $scriptRoot
    Invoke-LoaderChecked -Label '发布包框架自测' -Path (Join-Path $packageRoot 'SoD2SE.Loader.exe') -Arguments @('--self-test')
    Invoke-PythonChecked -Label '发布包源码一致性' -ScriptPath (Join-Path $packageRoot 'Automation/Check/verify_sources.py')
    Invoke-PythonChecked -Label '发布包协议一致性' -ScriptPath (Join-Path $packageRoot 'Automation/Check/verify_protocol.py')
    Invoke-PythonChecked -Label '发布包原生契约一致性' -ScriptPath (Join-Path $packageRoot 'Automation/Check/verify_native.py')
    Invoke-PythonChecked -Label '发布包逆向资料库' -ScriptPath (Join-Path $packageRoot 'Automation/Check/verify_research.py')
    Invoke-ResearchToolTests -ResearchDirectory (Join-Path $packageRoot 'Research')
    Invoke-PythonChecked -Label '发布包游戏静态校验' -ScriptPath (Join-Path $packageRoot 'Automation/Check/verify_game.py') -Arguments @($resolvedGameExe)
    Invoke-PythonChecked -Label '发布包原生招募逻辑' -ScriptPath (Join-Path $packageRoot 'Automation/Check/verify_recruitment.py') -Arguments @($resolvedGameExe)
    & (Join-Path $sourceRoot 'Automation\Test\run_memory_smoke.ps1') -GameExePath $resolvedGameExe -BuildDirectory $packageRoot
    if ($LASTEXITCODE -ne 0) { throw '发布包多插件/线程保护测试失败' }
    Invoke-PythonChecked -Label '发布包清单校验' -ScriptPath (Join-Path $packageRoot 'Automation/Check/verify_release.py')
    & (Join-Path $packageRoot 'source\Automation\Test\run_roguelite_smoke.ps1') -BuildDirectory $packageRoot
    if ($LASTEXITCODE -ne 0) { throw '发布包幸存者成长测试失败' }
    & (Join-Path $packageRoot 'source\Automation\Test\run_ui_smoke.ps1') -BuildDirectory $packageRoot
    if ($LASTEXITCODE -ne 0) { throw '发布包 UI 框架测试失败' }
    Write-Host 'PASS: 发布包离线回归完成'
    exit 0
}

$resolvedPackageDirectory = $ExecutionContext.SessionState.Path.GetUnresolvedProviderPathFromPSPath($PackageDirectory)
$resolvedZipPath = $ExecutionContext.SessionState.Path.GetUnresolvedProviderPathFromPSPath($ZipPath)
$packageScript = Join-Path $sourceRoot 'Automation/Package/package.ps1'
$buildScript = Join-Path $sourceRoot 'Automation/Build/build.ps1'
$compiled = Join-Path (Get-SoD2SEWorkRoot -SourceRoot $sourceRoot) 'build'
$temporaryRoot = Join-Path ([IO.Path]::GetTempPath()) ('SoD2SE-verify-' + [Guid]::NewGuid().ToString('N'))
$rebuildOutput = Join-Path $temporaryRoot 'rebuild'
$zipExtract = Join-Path $temporaryRoot 'zip'

try {
    Invoke-Checked -Label '开发目录构建' -Command {
        & $buildScript -OutputDirectory $compiled
    }.GetNewClosure()
    Invoke-LoaderChecked -Label '开发目录框架自测' -Path (Join-Path $compiled 'SoD2SE.Loader.exe') -Arguments @('--self-test')
    Invoke-PythonChecked -Label '开发目录源码一致性' -ScriptPath (Join-Path $sourceRoot 'Automation/Check/verify_sources.py')
    Invoke-PythonChecked -Label '开发目录协议一致性' -ScriptPath (Join-Path $sourceRoot 'Automation/Check/verify_protocol.py')
    Invoke-PythonChecked -Label '开发目录原生契约一致性' -ScriptPath (Join-Path $sourceRoot 'Automation/Check/verify_native.py')
    Invoke-PythonChecked -Label '开发目录逆向资料库' -ScriptPath (Join-Path $sourceRoot 'Automation/Check/verify_research.py')
    Invoke-ResearchToolTests -ResearchDirectory (Join-Path $sourceRoot 'Research')
    Invoke-PythonChecked -Label '开发目录游戏静态校验' -ScriptPath (Join-Path $sourceRoot 'Automation/Check/verify_game.py') -Arguments @($resolvedGameExe)
    Invoke-PythonChecked -Label '原生招募逻辑' -ScriptPath (Join-Path $sourceRoot 'Automation/Check/verify_recruitment.py') -Arguments @($resolvedGameExe)
    $meleeFixture = Join-Path (Get-SoD2SEWorkRoot -SourceRoot $sourceRoot) 'native/Release/MeleeNativeTest.exe'
    if (-not (Test-Path -LiteralPath $meleeFixture -PathType Leaf)) { throw "找不到原生近战分类器测试：$meleeFixture" }
    Invoke-Checked -Label '开发目录原生近战分类器' -Command { & $meleeFixture }.GetNewClosure()
    & (Join-Path $sourceRoot 'Automation\Test\run_roguelite_smoke.ps1') -BuildDirectory $compiled
    if ($LASTEXITCODE -ne 0) { throw '幸存者成长纯逻辑测试失败' }
    & (Join-Path $sourceRoot 'Automation\Test\run_ui_smoke.ps1') -BuildDirectory $compiled
    if ($LASTEXITCODE -ne 0) { throw 'UI 框架测试失败' }
    & (Join-Path $sourceRoot 'Automation\Test\run_memory_smoke.ps1') -GameExePath $resolvedGameExe -BuildDirectory $compiled
    if ($LASTEXITCODE -ne 0) { throw '多插件/线程保护测试失败' }

    Invoke-Checked -Label '重新生成发布包' -Command {
        & $packageScript -PackageDirectory $resolvedPackageDirectory -ZipPath $resolvedZipPath -CleanPackageDirectory
    }.GetNewClosure()
    Invoke-LoaderChecked -Label '发布目录框架自测' -Path (Join-Path $resolvedPackageDirectory 'SoD2SE.Loader.exe') -Arguments @('--self-test')
    Invoke-PythonChecked -Label '发布目录源码一致性' -ScriptPath (Join-Path $resolvedPackageDirectory 'Automation/Check/verify_sources.py')
    Invoke-PythonChecked -Label '发布目录协议一致性' -ScriptPath (Join-Path $resolvedPackageDirectory 'Automation/Check/verify_protocol.py')
    Invoke-PythonChecked -Label '发布目录原生契约一致性' -ScriptPath (Join-Path $resolvedPackageDirectory 'Automation/Check/verify_native.py')
    Invoke-PythonChecked -Label '发布目录逆向资料库' -ScriptPath (Join-Path $resolvedPackageDirectory 'Automation/Check/verify_research.py')
    Invoke-ResearchToolTests -ResearchDirectory (Join-Path $resolvedPackageDirectory 'Research')
    Invoke-PythonChecked -Label '发布目录游戏静态校验' -ScriptPath (Join-Path $resolvedPackageDirectory 'Automation/Check/verify_game.py') -Arguments @($resolvedGameExe)
    Invoke-PythonChecked -Label '发布目录清单校验' -ScriptPath (Join-Path $resolvedPackageDirectory 'Automation/Check/verify_release.py')

    [IO.Directory]::CreateDirectory($rebuildOutput) | Out-Null
    $rebuildSource = Join-Path $temporaryRoot 'rebuild-source'
    Copy-Item -LiteralPath (Join-Path $resolvedPackageDirectory 'source') -Destination $rebuildSource -Recurse
    Invoke-Checked -Label '发布包源码独立重编译' -Command {
        & (Join-Path $rebuildSource 'Automation/Build/build.ps1') -OutputDirectory $rebuildOutput
    }.GetNewClosure()
    Invoke-LoaderChecked -Label '独立重编译框架自测' -Path (Join-Path $rebuildOutput 'SoD2SE.Loader.exe') -Arguments @('--self-test')
    & (Join-Path $sourceRoot 'Automation\Test\run_roguelite_smoke.ps1') -BuildDirectory $rebuildOutput
    if ($LASTEXITCODE -ne 0) { throw '独立重编译幸存者成长测试失败' }
    & (Join-Path $sourceRoot 'Automation\Test\run_ui_smoke.ps1') -BuildDirectory $rebuildOutput
    if ($LASTEXITCODE -ne 0) { throw '独立重编译 UI 框架测试失败' }

    if (-not (Test-Path -LiteralPath $resolvedZipPath -PathType Leaf)) {
        throw "发布 ZIP 不存在：$resolvedZipPath"
    }
    [IO.Directory]::CreateDirectory($zipExtract) | Out-Null
    Expand-Archive -LiteralPath $resolvedZipPath -DestinationPath $zipExtract -Force
    Invoke-LoaderChecked -Label 'ZIP 解包框架自测' -Path (Join-Path $zipExtract 'SoD2SE.Loader.exe') -Arguments @('--self-test')
    Invoke-PythonChecked -Label 'ZIP 解包源码一致性' -ScriptPath (Join-Path $zipExtract 'Automation/Check/verify_sources.py')
    Invoke-PythonChecked -Label 'ZIP 解包协议一致性' -ScriptPath (Join-Path $zipExtract 'Automation/Check/verify_protocol.py')
    Invoke-PythonChecked -Label 'ZIP 解包原生契约一致性' -ScriptPath (Join-Path $zipExtract 'Automation/Check/verify_native.py')
    Invoke-PythonChecked -Label 'ZIP 解包逆向资料库' -ScriptPath (Join-Path $zipExtract 'Automation/Check/verify_research.py')
    Invoke-ResearchToolTests -ResearchDirectory (Join-Path $zipExtract 'Research')
    Invoke-PythonChecked -Label 'ZIP 解包游戏静态校验' -ScriptPath (Join-Path $zipExtract 'Automation/Check/verify_game.py') -Arguments @($resolvedGameExe)
    Invoke-PythonChecked -Label 'ZIP 解包清单校验' -ScriptPath (Join-Path $zipExtract 'Automation/Check/verify_release.py')

    Write-Host 'PASS: 多插件发布包回归完成'
} finally {
    if (Test-Path -LiteralPath $temporaryRoot) {
        $tempBoundary = [IO.Path]::GetFullPath([IO.Path]::GetTempPath()).TrimEnd('\') + '\'
        if (-not [IO.Path]::GetFullPath($temporaryRoot).StartsWith($tempBoundary, [StringComparison]::OrdinalIgnoreCase)) {
            throw "拒绝清理临时目录之外的路径：$temporaryRoot"
        }
        Remove-Item -LiteralPath $temporaryRoot -Recurse -Force
    }
}
