
$projectRoot = (Split-Path -Parent $PSScriptRoot)
# Shared lookups for the build, packaging, verification and install scripts.
#
# Two things used to be repeated in every script: the framework version and one
# developer machine's absolute paths.  Both now come from one place:
#   * FrameworkInfo.Version in Core/SoD2SE.Core.cs is the only version literal.
#   * the game executable and the MO2 instance are discovered, or named by the
#     caller through a parameter, an environment variable, or a small text file.
#
# Dot-source this file, then call the functions named below.

function Get-SoD2SEVersion {
    param([Parameter(Mandatory = $true)][string]$SourceRoot)

    $core = Join-Path $SourceRoot 'Core\SoD2SE.Core.cs'
    if (-not (Test-Path -LiteralPath $core -PathType Leaf)) {
        throw "找不到框架版本来源：$core"
    }
    $match = [regex]::Match((Get-Content -LiteralPath $core -Raw), 'public\s+const\s+string\s+Version\s*=\s*"([^"]+)"')
    if (-not $match.Success) {
        throw "无法从 $core 读取 FrameworkInfo.Version。"
    }
    return $match.Groups[1].Value
}

function Get-SoD2SEAssemblyVersion {
    # "0.6.0-preview" -> "0.6.0.0": the four-part version the CLR wants.  The
    # assembly attributes used to be written into eight AssemblyInfo.cs files,
    # which is how a package could ship a DLL stamped with another release.
    param([Parameter(Mandatory = $true)][string]$Version)

    $numeric = ($Version -split '-')[0]
    $parts = @($numeric.Split('.') | Where-Object { $_ -ne '' })
    if ($parts.Count -lt 1 -or $parts.Count -gt 4) {
        throw "无法从版本 $Version 推导程序集版本。"
    }
    foreach ($part in $parts) {
        if ($part -notmatch '^\d+$') { throw "无法从版本 $Version 推导程序集版本。" }
    }
    while ($parts.Count -lt 4) { $parts += '0' }
    return ($parts -join '.')
}

function Get-SoD2SEGameRelativePath {
    # Path of the shipping executable below a game root or below an MO2 mod root.
    return 'StateOfDecay2\Binaries\Win64\StateOfDecay2-Win64-Shipping.exe'
}

function Get-SteamLibraryRoots {
    $roots = New-Object System.Collections.Generic.List[string]
    $candidates = New-Object System.Collections.Generic.List[string]
    foreach ($name in 'ProgramFiles(x86)', 'ProgramFiles') {
        $base = [Environment]::GetEnvironmentVariable($name)
        if ($base) { $candidates.Add((Join-Path $base 'Steam')) }
    }
    foreach ($key in @('HKCU:\Software\Valve\Steam', 'HKLM:\SOFTWARE\WOW6432Node\Valve\Steam', 'HKLM:\SOFTWARE\Valve\Steam')) {
        try {
            $value = (Get-ItemProperty -Path $key -ErrorAction Stop).SteamPath
            if (-not $value) { $value = (Get-ItemProperty -Path $key -ErrorAction Stop).InstallPath }
            if ($value) { $candidates.Add($value) }
        } catch { }
    }
    foreach ($candidate in $candidates) {
        try { $roots.Add([IO.Path]::GetFullPath($candidate)) } catch { }
    }
    foreach ($root in @($roots)) {
        $libraries = Join-Path $root 'steamapps\libraryfolders.vdf'
        if (-not (Test-Path -LiteralPath $libraries -PathType Leaf)) { continue }
        foreach ($line in Get-Content -LiteralPath $libraries) {
            $match = [regex]::Match($line, '"path"\s*"([^"]+)"')
            if ($match.Success) {
                try { $roots.Add([IO.Path]::GetFullPath($match.Groups[1].Value.Replace('\\', '\'))) } catch { }
            }
        }
    }
    return ($roots | Select-Object -Unique)
}

function Resolve-SoD2GameExecutable {
    param([string]$GameExePath = '', [string]$HintFileDirectory = '')

    $relative = Get-SoD2SEGameRelativePath
    $tried = New-Object System.Collections.Generic.List[string]
    $candidates = New-Object System.Collections.Generic.List[string]
    $candidates.Add($GameExePath)
    $candidates.Add($env:SOD2_GAME_EXE)
    if ($env:SOD2_GAME_DIR) { $candidates.Add((Join-Path $env:SOD2_GAME_DIR $relative)) }
    if ($env:SOD2_GAME_DIR) { $candidates.Add((Join-Path $env:SOD2_GAME_DIR 'StateOfDecay2.exe')) }

    $hintRoots = @($HintFileDirectory, $projectRoot, (Get-Location).Path) |
        Where-Object { -not [string]::IsNullOrWhiteSpace($_) } | Select-Object -Unique
    foreach ($directory in $hintRoots) {
        foreach ($name in 'SoD2SE.GamePath.txt', 'SOD2SE_GAME_PATH.txt') {
            $hint = Join-Path $directory $name
            if (-not (Test-Path -LiteralPath $hint -PathType Leaf)) { continue }
            foreach ($line in Get-Content -LiteralPath $hint) {
                $value = $line.Trim()
                if (-not $value -or $value.StartsWith('#')) { continue }
                if (Test-Path -LiteralPath $value -PathType Container) {
                    $candidates.Add((Join-Path $value $relative))
                    $candidates.Add((Join-Path $value 'StateOfDecay2.exe'))
                } else {
                    $candidates.Add($value)
                }
            }
        }
    }

    foreach ($library in Get-SteamLibraryRoots) {
        $gameRoot = Join-Path $library 'steamapps\common\StateOfDecay2'
        $candidates.Add((Join-Path $gameRoot $relative))
        $candidates.Add((Join-Path $gameRoot 'StateOfDecay2.exe'))
    }

    foreach ($candidate in $candidates) {
        if ([string]::IsNullOrWhiteSpace($candidate)) { continue }
        try { $resolved = [IO.Path]::GetFullPath($candidate) } catch { continue }
        if ($tried -notcontains $resolved) { $tried.Add($resolved) }
        if (Test-Path -LiteralPath $resolved -PathType Leaf) { return $resolved }
    }
    throw ("找不到目标游戏主程序。" + [Environment]::NewLine +
        "请用 -GameExePath 指定，或设置 SOD2_GAME_EXE / SOD2_GAME_DIR，或把路径写进 SoD2SE.GamePath.txt。" +
        [Environment]::NewLine + "已尝试：" + [Environment]::NewLine + '  ' + ($tried -join ([Environment]::NewLine + '  ')))
}

function Get-SoD2GameDirectoryFromExecutable {
    param([Parameter(Mandatory = $true)][string]$GameExePath)

    # ...\StateOfDecay2\Binaries\Win64\Shipping.exe -> ...\StateOfDecay2
    $directory = Split-Path -Parent (Split-Path -Parent (Split-Path -Parent (Split-Path -Parent $GameExePath)))
    if (Test-Path -LiteralPath (Join-Path $directory 'StateOfDecay2.exe') -PathType Leaf) { return $directory }
    return (Split-Path -Parent $directory)
}

function Resolve-Mo2DataRoot {
    param([string]$MoDataRoot = '', [string]$HintFileDirectory = '')

    $tried = New-Object System.Collections.Generic.List[string]
    $candidates = New-Object System.Collections.Generic.List[string]
    $candidates.Add($MoDataRoot)
    $candidates.Add($env:SOD2_MO2_DATA)

    $hintRoots = @($HintFileDirectory, $projectRoot, (Get-Location).Path) |
        Where-Object { -not [string]::IsNullOrWhiteSpace($_) } | Select-Object -Unique
    foreach ($directory in $hintRoots) {
        foreach ($name in 'SoD2SE.Mo2Path.txt', 'SOD2SE_MO2_PATH.txt') {
            $hint = Join-Path $directory $name
            if (-not (Test-Path -LiteralPath $hint -PathType Leaf)) { continue }
            foreach ($line in Get-Content -LiteralPath $hint) {
                $value = $line.Trim()
                if (-not $value -or $value.StartsWith('#')) { continue }
                $candidates.Add($value)
            }
        }
    }

    foreach ($candidate in $candidates) {
        if ([string]::IsNullOrWhiteSpace($candidate)) { continue }
        try { $resolved = [IO.Path]::GetFullPath($candidate) } catch { continue }
        if ($tried -notcontains $resolved) { $tried.Add($resolved) }
        $hasMods = Test-Path -LiteralPath (Join-Path $resolved 'mods') -PathType Container
        $hasProfiles = Test-Path -LiteralPath (Join-Path $resolved 'profiles') -PathType Container
        if ($hasMods -and $hasProfiles) {
            return $resolved
        }
    }
    throw ("找不到 MO2 实例目录（需要同时包含 mods 和 profiles）。" + [Environment]::NewLine +
        "请用 -MoDataRoot 指定，或设置 SOD2_MO2_DATA，或把路径写进 SoD2SE.Mo2Path.txt。" +
        [Environment]::NewLine + "已尝试：" + [Environment]::NewLine + '  ' + ($tried -join ([Environment]::NewLine + '  ')))
}

function Get-SoD2SEWorkRoot {
    param([Parameter(Mandatory=$true)][string]$SourceRoot)
    $workspace = Split-Path -Parent (Split-Path -Parent $SourceRoot)
    if (Test-Path -LiteralPath (Join-Path $workspace 'workspace.toml')) {
        return (Join-Path $workspace '.work/SoD2SE')
    }
    return (Join-Path $SourceRoot '.work')
}
