# Rung 1 passed on seed 1: the premise started from a60d's actor swings up from rest and
# holds in 254 of 256 episodes. Seeds 2 and 3 of the same configuration run here so the
# success rate covers a fixed seed set. Each seed is scored at its last checkpoint.
# First, one from-rest trace of seed 1's policy: the gate reports the arm
# reaching 11.2 rad/s somewhere in the episode, twice the 5.4 rad/s of any bench capture with the pendulum caught, and
# the trace says where. Progress in runlogs\swingup06r5-status.log.
$py = "$env:USERPROFILE\Code\isaac\.venv\Scripts\python.exe"
$d = "$env:USERPROFILE\Code\isaac\furuta"
$log = "$d\runlogs\swingup06r5-status.log"
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
  # Read the log, not the exit code: this stack has returned 0 after a traceback.
  if (Select-String -Path $stepLog -SimpleMatch 'Traceback (most recent call last)' -Quiet) {
    Status "aborted: $stepName wrote a traceback"; exit 1
  }
}

& "$d\scripts\host\preflight.ps1" -Clear
if ($LASTEXITCODE -ne 0) { Status 'aborted: gpu busy'; exit 1 }

$common = 'scripts/train.py --headless --task Furuta-SwingUp-Direct-v0 ' +
          '--num-envs 1024 --physics-hz 4000 --max-iterations 600 ' +
          '--accel-bound 60 --max-rotor-rad 3.1416 ' +
          '--rotor-travel-deadband 0.5 --travel-weight -0.5 --rotor-rate-weight -0.01 ' +
          '--action-rate-weight -0.5 --pendulum-rate-weight -0.0096 ' +
          '--gamma 0.999 --episode-length-s 10 --no-value-clip'
$score = 'scripts/evaluate_swingup.py --headless --physics-hz 4000 --accel-bound 60 ' +
         '--num-envs 256'
$actor = 'logs/rsl_rl/furuta_balance_momentum/ar0p5/model_299.pt'

RunStep 'sw06r-r1-warm-trace' ('scripts/record_swingup_trace.py --headless --physics-hz 4000 ' +
  '--accel-bound 60 --num-envs 16 --seed 1 ' +
  '--checkpoint logs/rsl_rl/furuta_swingup/r1-warm/model_599.pt --out traces/sw06r_r1_warm.csv')

foreach ($seed in 2, 3) {
  RunStep "sw06r-r1-warm-seed$seed" "$common --seed $seed --init-from-actor $actor --run-name r1-warm-seed$seed"
  RunStep "sw06r-r1-warm-seed$seed-eval" ("$score --seed $seed " +
    "--checkpoint logs/rsl_rl/furuta_swingup/r1-warm-seed$seed/model_599.pt --out results/sw06r_r1_warm_seeds.csv")
}

Status 'SWINGUP06R5 DONE'
