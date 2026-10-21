# tame07r2: why tame-b cannot hold. tame-b swings up gently, the arm never past 0.72 rad
# and seven growing arcs like the kit's own pump, reaches vertical in 256 of 256 evaluation
# episodes, and holds 1. Two of its charges can tax the hold. The command-change charge
# applies inside the action-rate window, which defaults to the whole circle, so doubling it
# slows the reversals a catch needs. The travel charge has no threshold window at all, so a 0.15 rad
# deadband charges every correction the hold makes. Each run below restores one of those
# against tame-b and keeps everything else, so whichever holds names the cause.
# Progress in runlogs\tame07r2-status.log.
$py = "$env:USERPROFILE\Code\isaac\.venv\Scripts\python.exe"
$d = "$env:USERPROFILE\Code\isaac\furuta"
$log = "$d\runlogs\tame07r2-status.log"
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

# tame-b with the command-change charge back at -0.5, where every holding run had it
RunStep 'tame07r-tame-d' "scripts/train.py --headless --task Furuta-SwingUp-Direct-v0 --num-envs 1024 --physics-hz 4000 --seed 1 --max-iterations 600 --accel-bound 60 --pendulum-rate-weight -0.0096 --gamma 0.999 --episode-length-s 10 --episode-jitter 0.2 --no-value-clip --max-rotor-rad 3.1416 --travel-weight -5.0 --rotor-rate-weight -0.1 --rotor-travel-deadband 0.15 --action-rate-weight -0.5 --init-from-actor $actor --run-name tame-d"
RunStep 'tame07r-tame-d-eval' ("$score " + '--checkpoint logs/rsl_rl/furuta_swingup/tame-d/model_599.pt --out results/tame07r_tame-d.csv')
RunStep 'tame07r-tame-d-trace' 'scripts/record_swingup_trace.py --headless --physics-hz 4000 --accel-bound 60 --checkpoint logs/rsl_rl/furuta_swingup/tame-d/model_599.pt --out traces/tame07r_tame-d.csv'

# tame-b with the travel deadband widened to 0.5 rad, so the hold can correct freely while a big sweep still pays
RunStep 'tame07r-tame-e' "scripts/train.py --headless --task Furuta-SwingUp-Direct-v0 --num-envs 1024 --physics-hz 4000 --seed 1 --max-iterations 600 --accel-bound 60 --pendulum-rate-weight -0.0096 --gamma 0.999 --episode-length-s 10 --episode-jitter 0.2 --no-value-clip --max-rotor-rad 3.1416 --travel-weight -5.0 --rotor-rate-weight -0.1 --rotor-travel-deadband 0.5 --action-rate-weight -1.0 --init-from-actor $actor --run-name tame-e"
RunStep 'tame07r-tame-e-eval' ("$score " + '--checkpoint logs/rsl_rl/furuta_swingup/tame-e/model_599.pt --out results/tame07r_tame-e.csv')
RunStep 'tame07r-tame-e-trace' 'scripts/record_swingup_trace.py --headless --physics-hz 4000 --accel-bound 60 --checkpoint logs/rsl_rl/furuta_swingup/tame-e/model_599.pt --out traces/tame07r_tame-e.csv'

Status 'TAME07R2 DONE'
