# Milestone 04 reconciliation in PhysX, the whole set. Runs serially so nothing contends for the
# GPU. Launch it detached and watch runlogs\m4-status.log.
#
# Over SSH, Start-Process dies with the session. Create the process through WMI instead:
#   Invoke-CimMethod -ClassName Win32_Process -MethodName Create -Arguments @{
#     CommandLine = "powershell.exe -NoProfile -ExecutionPolicy Bypass -File <this>";
#     CurrentDirectory = "<checkout>" }
#
# Both paths are the host's own. Pass them in, or set the defaults below to match the
# layout in docs/runbooks/training-host-setup.md.
param(
  [string]$Python = "$PSScriptRoot\..\..\..\.venv\Scripts\python.exe",
  [string]$Checkout = "$PSScriptRoot\..\.."
)
$py  = (Resolve-Path $Python).Path
$d   = (Resolve-Path $Checkout).Path
$log = "$d\runlogs\m4-status.log"
# Without this the run blocks on the EULA prompt and still reports exit 0.
$env:OMNI_KIT_ACCEPT_EULA = 'YES'
$env:PYTHONPATH = "$d\src"
function Status($m) { Add-Content -Path $log -Value ((Get-Date -Format s) + ' ' + $m) }
function RunStep($name, $argstr) {
  Status "start $name"
  $cmd = "/c $py -u $argstr > $d\runlogs\$name.log 2>&1"
  $p = Start-Process -PassThru -Wait -FilePath 'cmd.exe' -ArgumentList $cmd -WorkingDirectory $d -WindowStyle Hidden
  Status "done $name exit=$($p.ExitCode)"
}
$trace = 'docs/experiments/03-hardware-bringup/trace.tsv'

# Refuse to start beside another run. Sharing the GPU is the largest wall-clock effect on
# this host and it leaves no trace in the log.
& "$d\scripts\host\preflight.ps1" -Clear
if ($LASTEXITCODE -ne 0) { Status 'aborted: gpu busy'; exit 1 }

Status 'm4 driver started'

# Dissipation: the same ladder the equation runs, before and after the reconciled terms.
RunStep 'qeff-before' 'scripts/diag_dissipation.py --headless --plant before --out results/qeff_before.csv'
RunStep 'qeff-after'  'scripts/diag_dissipation.py --headless --plant after  --out results/qeff_after.csv'

# The same two at the production rate. Free decay does not separate the physics rates:
# 1 kHz and 4 kHz agree to within 0.01 in Q at every amplitude bin.
RunStep 'qeff-before-1khz' 'scripts/diag_dissipation.py --headless --plant before --physics-hz 1000 --out results/qeff_before_1khz.csv'
RunStep 'qeff-after-1khz'  'scripts/diag_dissipation.py --headless --plant after  --physics-hz 1000 --out results/qeff_after_1khz.csv'

# Golden trace. The two gap profiles are two readings of what the capture leaves
# unmeasured. The 1 kHz run is the driven half of the physics-rate question.
RunStep 'replay-before'   "scripts/replay_trace.py --headless --plant before --trace $trace --out results/replay_before.csv"
RunStep 'replay-after'    "scripts/replay_trace.py --headless --plant after  --trace $trace --out results/replay_after.csv"
RunStep 'replay-bangbang' "scripts/replay_trace.py --headless --plant after --gap-profile bangbang --trace $trace --out results/replay_after_bangbang.csv"
RunStep 'replay-1khz'     "scripts/replay_trace.py --headless --plant after --physics-hz 1000 --trace $trace --out results/replay_after_1khz.csv"

# The swing-up joined to the balance hold. The hold logs at 5 Hz against a 136 ms
# instability time constant. This measures the log rate rather than the model.
RunStep 'full-bangbang' "scripts/replay_trace.py --headless --plant after --run all --gap-profile bangbang --trace $trace --out results/full_bangbang.csv"

# The write-up's clip, both gap profiles, for the side-by-side.
RunStep 'vid-linear'   "scripts/replay_trace.py --headless --plant after --gap-profile linear   --trace $trace --out results/vid_linear.csv --video videos/m4lin"
RunStep 'vid-bangbang' "scripts/replay_trace.py --headless --plant after --gap-profile bangbang --trace $trace --out results/vid_bang.csv  --video videos/m4bang"
Status 'M4 DONE'
