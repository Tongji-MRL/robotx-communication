[CmdletBinding()]
param(
    [ValidateRange(5, 300)]
    [int]$IntervalSeconds = 10
)

$ErrorActionPreference = 'Stop'
$mutexCreated = $false
$mutex = [System.Threading.Mutex]::new(
    $true,
    'RobotX-Orin-Time-Sync',
    [ref]$mutexCreated
)

if (-not $mutexCreated) {
    # The USV-only launcher was invoked more than once; retain one sync loop.
    exit 0
}

try {
    $syncScript = Join-Path $PSScriptRoot 'sync_orin_time.ps1'
    while ($true) {
        # A rebooted Orin initially has an invalid RTC clock.  SSH key
        # authentication remains available over the Mesh network, so retry
        # rather than requiring an operator to log in and set its time.
        & $syncScript *>$null
        Start-Sleep -Seconds $IntervalSeconds
    }
}
finally {
    $mutex.ReleaseMutex()
    $mutex.Dispose()
}
