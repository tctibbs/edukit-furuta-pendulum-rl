# The corrected-plant policy's catch map at its own simulated arrival, and the second
# bench session's capture replayed through the corrected plant.
# Progress in runlogs\swingup06r16-status.log.
$py = "$env:USERPROFILE\Code\isaac\.venv\Scripts\python.exe"
$d = "$env:USERPROFILE\Code\isaac\furuta"
$log = "$d\runlogs\swingup06r16-status.log"
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

# Run 9's checkpoint, not on the board, at the bound and rate it trained with. Every cell
# of a map shares the pendulum state given on its line. The first map is at run 9's own
# simulated arrival, and the arm state on its line moves the nearest grid cell onto itself.
# The upright map keeps the script's defaults, Session 1 attempt 1's arm state.
$map = 'scripts/evaluate_catch_map.py --headless --physics-hz 4000 --accel-bound 60 ' +
       '--num-envs 256 --seed 1'
RunStep 'sw06r-catch-map-smooth' ("$map --tilt-deg -3.0 --pendulum-rate 0.95 " +
  '--bench-arm-rad -0.43 --bench-arm-rate 3.69 --checkpoint logs/rsl_rl/furuta_swingup/r7-smooth/model_599.pt --out results/sw06r_catch_map_smooth.csv')
RunStep 'sw06r-catch-map-smooth-upright' ("$map --tilt-deg 0 --pendulum-rate 0 " +
  '--checkpoint logs/rsl_rl/furuta_swingup/r7-smooth/model_599.pt --out results/sw06r_catch_map_smooth_upright.csv')

# The slow-arm capture through the corrected plant: a second, independent check of the fix
# at 7.7 rad/s of arm speed, attempts 1 and 2.
$replay = 'scripts/replay_trace.py --headless --plant after --physics-hz 4000 ' +
          '--trace docs/experiments/06-swing-up/hardware/rl_swingup_20260910_session2_replay_input.tsv'
RunStep 'sw06r-session2-replay-0' "$replay --run 0 --out results/sw06r_session2_replay_run0.csv"
RunStep 'sw06r-session2-replay-1' "$replay --run 1 --out results/sw06r_session2_replay_run1.csv"

Status 'SWINGUP06R16 DONE'
