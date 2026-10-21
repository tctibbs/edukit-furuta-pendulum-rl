# tame07r4: tame-a over the seed set. tame-e's charges gave the tamest swing-up of the
# tame07 runs on seed 1 and then failed on both other seeds, one never arriving and one
# never holding, so that recipe is a lucky draw rather than a policy. tame-a is the milder
# version of the same idea, and it held 256 of 256 on seed 1. Seeds 2 and 3 of it.
# Progress in runlogs\tame07r4-status.log.
$py = "$env:USERPROFILE\Code\isaac\.venv\Scripts\python.exe"
$d = "$env:USERPROFILE\Code\isaac\furuta"
$log = "$d\runlogs\tame07r4-status.log"
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
$score = 'scripts/evaluate_swingup.py --headless --physics-hz 4000 --accel-bound 60 --num-envs 256'

RunStep 'tame07r-tame-a-seed2' "scripts/train.py --headless --task Furuta-SwingUp-Direct-v0 --num-envs 1024 --physics-hz 4000 --max-iterations 600 --accel-bound 60 --pendulum-rate-weight -0.0096 --gamma 0.999 --episode-length-s 10 --episode-jitter 0.2 --no-value-clip --max-rotor-rad 3.1416 --rotor-travel-deadband 0.25 --travel-weight -2.0 --rotor-rate-weight -0.05 --action-rate-weight -0.5 --seed 2 --init-from-actor $actor --run-name tame-a-seed2"
RunStep 'tame07r-tame-a-seed2-eval' ("$score --seed 2 " + '--checkpoint logs/rsl_rl/furuta_swingup/tame-a-seed2/model_599.pt --out results/tame07r_tame-a-seed2.csv')
RunStep 'tame07r-tame-a-seed2-trace' 'scripts/record_swingup_trace.py --headless --physics-hz 4000 --accel-bound 60 --checkpoint logs/rsl_rl/furuta_swingup/tame-a-seed2/model_599.pt --out traces/tame07r_tame-a-seed2.csv'

RunStep 'tame07r-tame-a-seed3' "scripts/train.py --headless --task Furuta-SwingUp-Direct-v0 --num-envs 1024 --physics-hz 4000 --max-iterations 600 --accel-bound 60 --pendulum-rate-weight -0.0096 --gamma 0.999 --episode-length-s 10 --episode-jitter 0.2 --no-value-clip --max-rotor-rad 3.1416 --rotor-travel-deadband 0.25 --travel-weight -2.0 --rotor-rate-weight -0.05 --action-rate-weight -0.5 --seed 3 --init-from-actor $actor --run-name tame-a-seed3"
RunStep 'tame07r-tame-a-seed3-eval' ("$score --seed 3 " + '--checkpoint logs/rsl_rl/furuta_swingup/tame-a-seed3/model_599.pt --out results/tame07r_tame-a-seed3.csv')
RunStep 'tame07r-tame-a-seed3-trace' 'scripts/record_swingup_trace.py --headless --physics-hz 4000 --accel-bound 60 --checkpoint logs/rsl_rl/furuta_swingup/tame-a-seed3/model_599.pt --out traces/tame07r_tame-a-seed3.csv'

Status 'TAME07R4 DONE'
