[CmdletBinding()]
param([string]$GameRoot = '')
$ErrorActionPreference = 'Stop'
if (-not $GameRoot) {
    Add-Type -AssemblyName System.Windows.Forms
    $dialog = New-Object System.Windows.Forms.FolderBrowserDialog
    $dialog.Description = '选择腐烂国度 2 游戏根目录 / Select the State of Decay 2 game root'
    if ($dialog.ShowDialog() -ne 'OK') { return }
    $GameRoot = $dialog.SelectedPath
    $dialog.Dispose()
}
& (Join-Path $PSScriptRoot 'Root/SoD2SE.DevTools.exe') install (Join-Path $PSScriptRoot 'Root') $GameRoot
if ($LASTEXITCODE -ne 0) { throw 'SoD2SE installation refused. See the diagnostic message.' }
