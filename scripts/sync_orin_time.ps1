[CmdletBinding()]
param(
    [string]$OrinHost = '192.168.206.66',
    [string]$OrinUser = 'robotx',
    [string]$KeyPath = (Join-Path $env:USERPROFILE '.ssh\robotx_orin_time_sync'),
    [ValidateRange(1, 30)]
    [int]$ConnectTimeoutSeconds = 8
)

$ErrorActionPreference = 'Stop'
$ssh = Join-Path $env:WINDIR 'System32\OpenSSH\ssh.exe'

if (-not (Test-Path -LiteralPath $ssh)) {
    throw "OpenSSH client was not found: $ssh"
}
if (-not (Test-Path -LiteralPath $KeyPath)) {
    throw "Orin time-sync key was not found: $KeyPath"
}

# Evaluate immediately before SSH dispatch so the value is not affected by
# interactive password entry or manual copy/paste latency.
$utc = [DateTime]::UtcNow.ToString('yyyy-MM-ddTHH:mm:ss.fffZ')
$target = "${OrinUser}@${OrinHost}"
$output = & $ssh `
    -i $KeyPath `
    -o BatchMode=yes `
    -o StrictHostKeyChecking=accept-new `
    -o "ConnectTimeout=$ConnectTimeoutSeconds" `
    $target "robotx-time-sync $utc" 2>&1

if ($LASTEXITCODE -ne 0) {
    $details = ($output | Out-String).Trim()
    throw "Orin time synchronization failed: $details"
}

$output | ForEach-Object { Write-Host $_ }
