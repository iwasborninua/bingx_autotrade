param(
    [switch]$Force
)

$ErrorActionPreference = "Stop"
$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$LockFiles = @(
    Join-Path $ProjectRoot "bingx_autotrade_telethon.lock"
)

$processes = Get-CimInstance Win32_Process |
    Where-Object {
        $_.ProcessId -ne $PID -and
        $_.Name -like "python*" -and
        $_.CommandLine -like "*$ProjectRoot*"
    }

if (-not $processes) {
    Write-Host "No project Python processes found."
} else {
    Write-Host "Project Python processes:"
    $processes | Select-Object ProcessId, Name, CommandLine | Format-Table -AutoSize

    if (-not $Force) {
        $answer = Read-Host "Stop these processes? Type YES to continue"
        if ($answer -ne "YES") {
            Write-Host "Canceled."
            exit 0
        }
    }

    foreach ($process in $processes) {
        Stop-Process -Id $process.ProcessId -Force
        Write-Host "Stopped PID $($process.ProcessId)"
    }
}

foreach ($lockFile in $LockFiles) {
    if (Test-Path -LiteralPath $lockFile) {
        Remove-Item -LiteralPath $lockFile -Force
        Write-Host "Removed lock: $lockFile"
    }
}
