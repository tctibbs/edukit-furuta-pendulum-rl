# tame07r1: a tame swing-up. Experiment 06's fastest policy sweeps the arm to 2.8 rad at
# 11 rad/s in one stroke, which is quick and looks violent, and an arm that far out is the
# one that walks into the cable bind. Slower is acceptable here. Each run raises the price
# of arm travel, and the third bounds travel outright at 1.6 rad rather than pricing it, so
# the policy cannot reach the cable at all. Everything else is the corrected-plant
# configuration (ADR-0006) of Experiment 06's run 9, seed 1.
# Progress in runlogs\tame07r1-status.log.
$py = "$env:USERPROFILE\Code\isaac\.venv\Scripts\python.exe"
$d = "$env:USERPROFILE\Code\isaac\furuta"
$log = "$d\runlogs\tame07r1-status.log"
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

$actor = 'logs/rsl_rl/furuta_balance_momentum/ar0p5/model_299.pt'
$score = 'scripts/evaluate_swingup.py --headless --physics-hz 4000 --accel-bound 60 --num-envs 256 --seed 1'

# travel priced four times harder inside a tighter deadband, arm speed five times
RunStep 'tame07r-tame-a' "scripts/train.py --headless --task Furuta-SwingUp-Direct-v0 --num-envs 1024 --physics-hz 4000 --seed 1 --max-iterations 600 --accel-bound 60 --pendulum-rate-weight -0.0096 --gamma 0.999 --episode-length-s 10 --episode-jitter 0.2 --no-value-clip --max-rotor-rad 3.1416 --rotor-travel-deadband 0.25 --travel-weight -2.0 --rotor-rate-weight -0.05 --action-rate-weight -0.5 --init-from-actor $actor --run-name tame-a"
RunStep 'tame07r-tame-a-eval' ("$score  " + '--checkpoint logs/rsl_rl/furuta_swingup/tame-a/model_599.pt --out results/tame07r_tame-a.csv')
RunStep 'tame07r-tame-a-trace' 'scripts/record_swingup_trace.py --headless --physics-hz 4000 --accel-bound 60  --checkpoint logs/rsl_rl/furuta_swingup/tame-a/model_599.pt --out traces/tame07r_tame-a.csv'

# the same pushed further, plus a heavier charge on changing the command
RunStep 'tame07r-tame-b' "scripts/train.py --headless --task Furuta-SwingUp-Direct-v0 --num-envs 1024 --physics-hz 4000 --seed 1 --max-iterations 600 --accel-bound 60 --pendulum-rate-weight -0.0096 --gamma 0.999 --episode-length-s 10 --episode-jitter 0.2 --no-value-clip --max-rotor-rad 3.1416 --rotor-travel-deadband 0.15 --travel-weight -5.0 --rotor-rate-weight -0.1 --action-rate-weight -1.0 --init-from-actor $actor --run-name tame-b"
RunStep 'tame07r-tame-b-eval' ("$score  " + '--checkpoint logs/rsl_rl/furuta_swingup/tame-b/model_599.pt --out results/tame07r_tame-b.csv')
RunStep 'tame07r-tame-b-trace' 'scripts/record_swingup_trace.py --headless --physics-hz 4000 --accel-bound 60  --checkpoint logs/rsl_rl/furuta_swingup/tame-b/model_599.pt --out traces/tame07r_tame-b.csv'

# run a with the travel bound halved to 1.6 rad, so the episode ends before the cable can bind
RunStep 'tame07r-tame-c' "scripts/train.py --headless --task Furuta-SwingUp-Direct-v0 --num-envs 1024 --physics-hz 4000 --seed 1 --max-iterations 600 --accel-bound 60 --pendulum-rate-weight -0.0096 --gamma 0.999 --episode-length-s 10 --episode-jitter 0.2 --no-value-clip --max-rotor-rad 1.6 --rotor-travel-deadband 0.25 --travel-weight -2.0 --rotor-rate-weight -0.05 --action-rate-weight -0.5 --init-from-actor $actor --run-name tame-c"
RunStep 'tame07r-tame-c-eval' ("$score --max-rotor-rad 1.6 " + '--checkpoint logs/rsl_rl/furuta_swingup/tame-c/model_599.pt --out results/tame07r_tame-c.csv')
RunStep 'tame07r-tame-c-trace' 'scripts/record_swingup_trace.py --headless --physics-hz 4000 --accel-bound 60 --max-rotor-rad 1.6 --checkpoint logs/rsl_rl/furuta_swingup/tame-c/model_599.pt --out traces/tame07r_tame-c.csv'

Status 'TAME07R1 DONE'
