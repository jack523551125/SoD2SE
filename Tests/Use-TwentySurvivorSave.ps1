[CmdletBinding()]
param(
    [ValidateSet('Apply','Restore','Check')][string]$Action = 'Check',
    [string]$SaveDirectory = "$env:LOCALAPPDATA\StateOfDecay2\Saved\Steam\76561199522486171\2535459487534871\Release\v2"
)
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$target = (Resolve-Path -LiteralPath $SaveDirectory).ProviderPath
$names = @('SaveGame_Vanilla_0.sav','SaveUser.sav')
$statePath = Join-Path $PSScriptRoot 'active-test.json'
if (Get-Process -Name 'StateOfDecay2','StateOfDecay2-Win64-Shipping','SoD2SE.Loader' -ErrorAction SilentlyContinue) {
    throw 'Exit the game and SoD2SE Loader before switching saves.'
}
foreach ($name in $names) {
    foreach ($dir in @($target,(Join-Path $PSScriptRoot 'Original'),(Join-Path $PSScriptRoot 'Test20'))) {
        if (!(Test-Path -LiteralPath (Join-Path $dir $name) -PathType Leaf)) { throw "Missing save: $dir\$name" }
    }
}
if ($Action -eq 'Check') { Write-Output "Ready. Community slot 0 and SaveUser will be switched together. Target: $target"; return }
if ($Action -eq 'Apply') {
    if (Test-Path -LiteralPath $statePath) { throw 'A test session is already active. Restore it first.' }
    foreach ($name in $names) {
        if ((Get-FileHash -LiteralPath (Join-Path $target $name)).Hash -ne (Get-FileHash -LiteralPath (Join-Path $PSScriptRoot "Original\$name")).Hash) {
            throw 'Your live save has changed since the fixture was made. Nothing was overwritten. Regenerate the fixture from the current save.'
        }
    }
    $source = Join-Path $PSScriptRoot 'Test20'
} else {
    if (!(Test-Path -LiteralPath $statePath)) { throw 'No active test backup was found.' }
    $state = Get-Content -LiteralPath $statePath -Raw | ConvertFrom-Json
    if ($state.target -ne $target) { throw 'Backup target mismatch.' }
    $source = $state.backup
    foreach ($name in $names) {
        if ((Get-FileHash -LiteralPath (Join-Path $source $name)).Hash -ne $state.hashes.$name) { throw 'Backup integrity check failed.' }
    }
}
$backup = Join-Path $PSScriptRoot ('Backups\' + $Action + '-' + [DateTime]::Now.ToString('yyyyMMdd-HHmmss') + '-' + [Guid]::NewGuid().ToString('N'))
[IO.Directory]::CreateDirectory($backup) | Out-Null
$hashes = @{}
foreach ($name in $names) {
    Copy-Item -LiteralPath (Join-Path $target $name) -Destination (Join-Path $backup $name)
    $hashes[$name] = (Get-FileHash -LiteralPath (Join-Path $backup $name)).Hash
}
# Journal is durable before either save changes. A partially completed Apply
# can always be recovered using Restore; Restore never deletes its backup.
if ($Action -eq 'Apply') {
    @{target=$target;backup=$backup;hashes=$hashes} | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath $statePath -Encoding UTF8
}
$changed = @()
try {
    foreach ($name in $names) {
        $destination = Join-Path $target $name
        $temp = $destination + '.' + [Guid]::NewGuid().ToString('N') + '.tmp'
        try {
            Copy-Item -LiteralPath (Join-Path $source $name) -Destination $temp
            [IO.File]::Replace($temp,$destination,(Join-Path $backup ($name + '.replaced')))
            $changed += $name
        } finally { if (Test-Path -LiteralPath $temp) { Remove-Item -LiteralPath $temp } }
    }
    foreach ($name in $names) {
        if ((Get-FileHash -LiteralPath (Join-Path $target $name)).Hash -ne (Get-FileHash -LiteralPath (Join-Path $source $name)).Hash) { throw 'Installed save hash mismatch.' }
    }
} catch {
    foreach ($name in $changed) { Copy-Item -LiteralPath (Join-Path $backup $name) -Destination (Join-Path $target $name) -Force }
    throw
}
if ($Action -eq 'Restore') { Remove-Item -LiteralPath $statePath }
Write-Output "$Action completed. Previous files preserved at: $backup"
