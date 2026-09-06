# Refuse to start a GPU run when the GPU is not free. Source or call this before a queue.
#
# The largest wall-clock effect on this host is a second job running beside the first, and
# it is invisible from inside either one: two identical trainings measured 10.86 s per
# iteration each against 5.27 s alone. One run that shared the machine for an afternoon
# averaged 89.7 s and took ten hours for work that takes thirty-five minutes with the
# machine to itself.
#
# Leftovers from the shutdown hang are a separate and much smaller thing. Four idle ones
# cost 7 percent. They are reported and cleared rather than treated as a blocker.
#
# Usage:
#   .\scripts\host\preflight.ps1            # report and exit 1 if busy
#   .\scripts\host\preflight.ps1 -Clear     # also kill idle leftovers first
#   .\scripts\host\preflight.ps1 -Force     # report but never block
param([switch]$Clear, [switch]$Force)

$ErrorActionPreference = 'Stop'

# Only the Isaac install's interpreter counts. Any python whose command line mentions a
# `Scripts\` directory used to count, and a desktop tool's unrelated venv on this machine
# blocked a launch that way.
function Get-IsaacProcesses {
    Get-CimInstance Win32_Process |
        Where-Object { $_.Name -eq 'python.exe' -and $_.CommandLine -match 'Code[\\/]isaac[\\/]' }
}

# Isaac launches a child interpreter, so the raw process count is about double the number
# of actual jobs. Keep only the ones whose parent is not itself one of these. One entry
# per job is what the slowdown factor below assumes.
function Get-IsaacJobs {
    $all = @(Get-IsaacProcesses)
    $ids = $all | ForEach-Object { $_.ProcessId }
    $all | Where-Object { $ids -notcontains $_.ParentProcessId }
}

$running = @(Get-IsaacJobs)
$mem = (nvidia-smi --query-gpu=memory.used,memory.total --format=csv,noheader) -join ''

Write-Output "[preflight] gpu memory: $mem"
Write-Output "[preflight] isaac jobs running: $($running.Count)"

foreach ($p in $running) {
    $age = [int]((Get-Date) - $p.CreationDate).TotalMinutes
    $what = ($p.CommandLine -split '\s+' | Where-Object { $_ -match '\.py$' } | Select-Object -First 1)
    Write-Output ("  pid {0,-7} {1,5} min  {2}" -f $p.ProcessId, $age, $what)
}

if ($Clear -and $running.Count -gt 0) {
    # Only the ones old enough that they cannot be a job someone just started.
    $stale = $running | Where-Object { ((Get-Date) - $_.CreationDate).TotalMinutes -gt 60 }
    foreach ($p in $stale) {
        Write-Output "[preflight] clearing stale pid $($p.ProcessId)"
        Stop-Process -Id $p.ProcessId -Force -ErrorAction SilentlyContinue
    }
    Start-Sleep -Seconds 3
    $running = @(Get-IsaacJobs)
}

if ($running.Count -gt 0) {
    Write-Output "[preflight] BUSY. A run started now would take about $($running.Count + 1) times as long,"
    Write-Output "[preflight] and so would whatever is already running. Wait, or clear the list above."
    if (-not $Force) { exit 1 }
    Write-Output "[preflight] -Force given, continuing anyway"
}
else {
    Write-Output "[preflight] clear"
}
exit 0
