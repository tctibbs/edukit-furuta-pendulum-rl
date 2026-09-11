# Clips for the write-up: nine rigs from hanging under the control policy, which reaches
# the top and rotates over it, and nine under seed 1's warm-started policy, which swings
# up and holds. Each clip runs 10 s at 4 kHz with the bound the policies trained at; the
# recorder gained --accel-bound for this. Without it a 60 rad/s^2 policy plays at
# 11.78 rad/s^2 and the clip shows a pump that never existed.
# Progress in runlogs\swingup06r8-status.log.
$py = "$env:USERPROFILE\Code\isaac\.venv\Scripts\python.exe"
$d = "$env:USERPROFILE\Code\isaac\furuta"
$log = "$d\runlogs\swingup06r8-status.log"
$env:OMNI_KIT_ACCEPT_EULA = 'YES'
$env:PYTHONPATH = "$d\src"

function Status($m) { Add-Content -Path $log -Value ((Get-Date -Format s) + ' ' + $m) }

function RunStep($stepName, $argstr) {
  Status "start $stepName"
  $stepLog = "$d\runlogs\$stepName.log"
  $cmd = "/c $py -u $argstr > $stepLog 2>&1"
  $proc = Start-Process -PassThru -Wait -FilePath 'cmd.exe' -ArgumentList $cmd `
    -WorkingDirectory $d -WindowStyle Hidden
  Status "done $stepName exit=$($proc.ExitCode)"
  if ($proc.ExitCode -ne 0) { Status "aborted: $stepName failed"; exit 1 }
  if (Select-String -Path $stepLog -SimpleMatch 'Traceback (most recent call last)' -Quiet) {
    Status "aborted: $stepName wrote a traceback"; exit 1
  }
}

& "$d\scripts\host\preflight.ps1" -Clear
if ($LASTEXITCODE -ne 0) { Status 'aborted: gpu busy'; exit 1 }

$rec = 'scripts/record_policy.py --headless --task Furuta-SwingUp-Direct-Play-v0 --start hanging ' +
       '--swingup-camera --physics-hz 4000 --accel-bound 60 --num-envs 9 --steps 5000'

RunStep 'sw06r-clip-control' "$rec --checkpoint logs/rsl_rl/furuta_swingup/r1-scratch/model_599.pt --output videos/sw06r/control"
RunStep 'sw06r-clip-warm' "$rec --checkpoint logs/rsl_rl/furuta_swingup/r1-warm/model_599.pt --output videos/sw06r/warm"
RunStep 'sw06r-clip-clock' "$rec --checkpoint logs/rsl_rl/furuta_swingup/r3-clock/model_599.pt --output videos/sw06r/clock"

# The clock rung's policy from rest, per step, for the overlay against the bench capture of
# the same policy taken on 2026-09-10.
RunStep 'sw06r-trace-clock' 'scripts/record_swingup_trace.py --headless --physics-hz 4000 --accel-bound 60 --checkpoint logs/rsl_rl/furuta_swingup/r3-clock/model_599.pt --out traces/sw06r_r3_clock.csv'

# The trace the model-conversion gate replays: the clock rung's policy in command from
# the first step of a hanging start, through the tanh it trained with. Opening the catch
# region to the whole circle hands the scripted swing-up's control to the policy at step
# zero, and the trace carries the observations and the acceleration the simulation
# applied on every row.
RunStep 'sw06r-gate-trace' ('scripts/scripted_swingup.py --headless --physics-hz 4000 --num-envs 16 --seed 1 ' +
  '--duration-s 10 --accel-bound 60 --policy-bound 60 --catch-tilt 3.2 --catch-mode 1000 --catch-squash ' +
  '--checkpoint logs/rsl_rl/furuta_swingup/r3-clock/model_599.pt --policy-task Furuta-SwingUp-Direct-Play-v0 ' +
  '--trace results/sw06r_gate_trace_r3_clock.csv --out results/sw06r_gate_trace.csv')

Status 'SWINGUP06R8 DONE'
