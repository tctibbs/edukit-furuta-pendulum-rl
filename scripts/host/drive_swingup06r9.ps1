# Replay the 2026-09-10 bench capture of the swing-up policy through the PhysX plant,
# both attempts, after the clips job. Progress in runlogs\swingup06r9-status.log.
$py = "$env:USERPROFILE\Code\isaac\.venv\Scripts\python.exe"
$d = "$env:USERPROFILE\Code\isaac\furuta"
$log = "$d\runlogs\swingup06r9-status.log"
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

# The bench capture of 2026-09-10 (the clock rung's policy, mode r, from rest) replayed
# through the PhysX articulation: the rotor follows the motion the board dead-reckoned,
# the pendulum is free, so any gap between the simulated tilt and the measured one is the
# plant or the stepper not following its own dead reckoning, and not the policy. Runs 0
# and 1 are the two attempts whose fast log covers the swing-up and the catch.
$replay = 'scripts/replay_trace.py --headless --plant after --stepped-rotor --physics-hz 4000 ' +
          '--trace docs/experiments/06-swing-up/hardware/rl_swingup_20260910_replay_input.tsv'
RunStep 'sw06r-bench-replay-0' "$replay --run 0 --out results/sw06r_bench_replay_run0.csv"
RunStep 'sw06r-bench-replay-1' "$replay --run 1 --out results/sw06r_bench_replay_run1.csv"

Status 'SWINGUP06R9 DONE'
