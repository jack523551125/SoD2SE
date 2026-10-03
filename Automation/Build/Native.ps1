[CmdletBinding()]
param(
    [Parameter(Mandatory=$true)][string]$OutputDirectory,
    [Parameter(Mandatory=$true)][string]$MeleeOutputDirectory
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$build = Join-Path $PSScriptRoot 'build'
$release = Join-Path $build 'Release'
# Both native components are required.  They were produced by one CMake tree,
# which meant a failed melee build could leave last session's DLL behind and
# get copied into the package, so each target names its own destination and the
# products are deleted before the build.
$targets = @(
    [pscustomobject]@{ Name = 'SoD2SE.Mcm.Native.dll'; Source = 'McmNative.cpp'; Extra = $true; Destination = $OutputDirectory },
    [pscustomobject]@{ Name = 'SoD2SE.MeleeSpeed.Native.dll'; Source = 'MeleeNative.cpp'; Extra = $false; Destination = $MeleeOutputDirectory }
)

function Invoke-CMakeBuild {
    & cmake -S $PSScriptRoot -B $build -G 'Visual Studio 17 2022' -A x64 | Out-Host
    if ($LASTEXITCODE -ne 0) { return $false }
    & cmake --build $build --config Release --parallel | Out-Host
    return ($LASTEXITCODE -eq 0)
}

function Get-VcVarsPath {
    $vcvars = Join-Path ${env:ProgramFiles} 'Microsoft Visual Studio\2022\Community\VC\Auxiliary\Build\vcvarsall.bat'
    if (-not (Test-Path -LiteralPath $vcvars -PathType Leaf)) {
        $vswhere = Join-Path ${env:ProgramFiles(x86)} 'Microsoft Visual Studio\Installer\vswhere.exe'
        if (Test-Path -LiteralPath $vswhere -PathType Leaf) {
            $installation = (& $vswhere -latest -products * -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -property installationPath | Select-Object -First 1)
            if ($installation) { $vcvars = Join-Path $installation.Trim() 'VC\Auxiliary\Build\vcvarsall.bat' }
        }
    }
    if (-not (Test-Path -LiteralPath $vcvars -PathType Leaf)) { throw '找不到 vcvarsall.bat，无法回退到 cl.exe 直接编译。' }
    return $vcvars
}

# MSBuild's file tracker builds a case-insensitive dictionary of the process
# environment and throws when the block carries both "Path" and "PATH".  Some
# launchers and CI harnesses do exactly that, so fall back to calling cl.exe
# directly; the compiler never uses the tracker.
function Invoke-DirectCompile {
    $vcvars = Get-VcVarsPath
    $objectDirectory = Join-Path $build 'obj-direct'
    [IO.Directory]::CreateDirectory($objectDirectory) | Out-Null
    [IO.Directory]::CreateDirectory($release) | Out-Null

    $minhook = @(
        'vendor\minhook\src\buffer.c', 'vendor\minhook\src\hook.c', 'vendor\minhook\src\trampoline.c',
        'vendor\minhook\src\hde\hde32.c', 'vendor\minhook\src\hde\hde64.c')
    $imgui = @(
        'vendor\imgui\imgui.cpp', 'vendor\imgui\imgui_draw.cpp',
        'vendor\imgui\imgui_tables.cpp', 'vendor\imgui\imgui_widgets.cpp',
        'vendor\imgui\backends\imgui_impl_win32.cpp', 'vendor\imgui\backends\imgui_impl_dx11.cpp')

    foreach ($target in $targets) {
        $sources = @($target.Source) + $minhook
        $libraries = @('user32.lib')
        if ($target.Extra) { $sources += $imgui; $libraries += @('d3d11.lib', 'dxgi.lib', 'd3dcompiler.lib') }
        $output = Join-Path $release $target.Name
        $importLibrary = Join-Path $release ([IO.Path]::GetFileNameWithoutExtension($target.Name) + '.lib')
        $arguments = @(
            'cl', '/nologo', '/utf-8', '/W4', '/EHa', '/O2', '/MT', '/LD',
            ('/Fo:' + $objectDirectory + '\'),
            '/DWIN32_LEAN_AND_MEAN', '/DNOMINMAX', '/DUNICODE', '/D_UNICODE',
            '/I', 'vendor\imgui', '/I', 'vendor\imgui\backends',
            '/I', 'vendor\minhook\include', '/I', 'vendor\minhook\src', '/I', 'vendor\minhook\src\hde'
        ) + ($sources | ForEach-Object { Join-Path $PSScriptRoot $_ }) + @(
            '/link', ('/OUT:' + $output), ('/IMPLIB:' + $importLibrary)
        ) + $libraries

        $batch = Join-Path ([IO.Path]::GetTempPath()) ('SoD2SE-native-' + [Guid]::NewGuid().ToString('N') + '.bat')
        $batchLines = New-Object System.Collections.Generic.List[string]
        $batchLines.Add('@echo off')
        $batchLines.Add('call "' + $vcvars + '" x64')
        $batchLines.Add('if errorlevel 1 exit /b 1')
        $batchLines.Add('cd /d "' + $PSScriptRoot + '"')
        $batchLines.Add(($arguments | ForEach-Object { if ($_ -match '\s') { '"' + $_ + '"' } else { $_ } }) -join ' ')
        $batchLines.Add('exit /b %errorlevel%')
        [IO.File]::WriteAllLines($batch, $batchLines, [Text.Encoding]::ASCII)
        try {
            & cmd.exe /c $batch
            if ($LASTEXITCODE -ne 0) { throw "cl.exe 直接编译失败（$($target.Name)）：$LASTEXITCODE" }
        }
        finally {
            if (Test-Path -LiteralPath $batch) { Remove-Item -LiteralPath $batch -Force }
        }
    }
}

# Delete this session's products first: the existence check below must prove the
# build wrote them, not that an older DLL was still lying around.
[IO.Directory]::CreateDirectory($release) | Out-Null
foreach ($target in $targets) { Remove-Item -LiteralPath (Join-Path $release $target.Name) -Force -ErrorAction SilentlyContinue }

$built = $false
try { $built = Invoke-CMakeBuild } catch { $built = $false }
if (-not $built) {
    Write-Warning 'MSBuild 构建失败；回退到 cl.exe 直接编译原生组件。'
    Invoke-DirectCompile
}

foreach ($target in $targets) {
    $product = Join-Path $release $target.Name
    if (-not (Test-Path -LiteralPath $product -PathType Leaf)) { throw "找不到原生构建产物：$product" }
    # Resolve through PowerShell: [IO.Path]::GetFullPath follows the process
    # working directory, which a "cd" in the calling script does not change, so
    # a relative destination used to land in the launcher's directory.
    $destination = $ExecutionContext.SessionState.Path.GetUnresolvedProviderPathFromPSPath($target.Destination)
    [IO.Directory]::CreateDirectory($destination) | Out-Null
    Copy-Item -LiteralPath $product -Destination $destination -Force
}
