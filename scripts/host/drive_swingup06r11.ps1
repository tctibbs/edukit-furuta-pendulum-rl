# Where the clock rung's catch holds, over the arm states the bench arrived in. On
# 2026-09-10 the policy had the real pendulum inside 3 degrees at 1.7 s with the arm past
# 1 rad and moving at 4.2 to 4.7 rad/s, then let it drift through zero and fall while
# commanding -4 to -9 rad/s^2. The board's commands replay exactly from its observations,
# so the question is whether the policy holds from that arrival in the simulation. Each
# run fixes the pendulum at one arrival and sweeps the arm over a 16 by 16 grid of angle
# by rate: (a) attempt 1's pendulum state, (b) attempt 2's, (c) upright at rest as the
# control. A bench cell that holds here puts the gap in the plant or the stepper; one that
# does not says the policy cannot catch from where its own swing-up arrives, and the fix
# is training-side. Progress in runlogs\swingup06r11-status.log.
$py = "$env:USERPROFILE\Code\isaac\.venv\Scripts\python.exe"
$d = "$env:USERPROFILE\Code\isaac\furuta"
$log = "$d\runlogs\swingup06r11-status.log"
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

# The same checkpoint the board runs, at the bound and rate it trained with. Every cell
# of a run shares the pendulum state given on its line; the bench arm state on the line
# moves the nearest grid cell onto itself, so run (a) reads attempt 1's exact arrival
# and run (b) attempt 2's, which on the default axes would otherwise share one column.
# Run (c) keeps the script's defaults, which are attempt 1's arm state.
$map = 'scripts/evaluate_catch_map.py --headless --physics-hz 4000 --accel-bound 60 --stepped-rotor ' +
       '--num-envs 256 --seed 1 --checkpoint logs/rsl_rl/furuta_swingup/r3-clock/model_599.pt'
RunStep 'sw06r-catch-map-a1' ("$map --tilt-deg 2.85 --pendulum-rate -0.33 " +
  '--bench-arm-rad 1.42 --bench-arm-rate 4.21 --out results/sw06r_catch_map_a1.csv')
RunStep 'sw06r-catch-map-a2' ("$map --tilt-deg 2.85 --pendulum-rate -1.50 " +
  '--bench-arm-rad 1.04 --bench-arm-rate 4.65 --out results/sw06r_catch_map_a2.csv')
RunStep 'sw06r-catch-map-upright' ("$map --tilt-deg 0 --pendulum-rate 0 " +
  '--out results/sw06r_catch_map_upright.csv')

Status 'SWINGUP06R11 DONE'
