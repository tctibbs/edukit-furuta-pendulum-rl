# tame07r3: tame-e over the seed set. tame-e holds 256 of 256 on seed 1 with the arm
# never past 1.04 rad and seven growing arcs, which is the tame swing-up the tame07 runs
# were for, but one seed is not a result in this project. Seeds 2 and 3 of the same
# configuration.
# Progress in runlogs\tame07r3-status.log.
$py = "$env:USERPROFILE\Code\isaac\.venv\Scripts\python.exe"
$d = "$env:USERPROFILE\Code\isaac\furuta"
$log = "$d\runlogs\tame07r3-status.log"
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

RunStep 'tame07r-tame-e-seed2' "scripts/train.py --headless --task Furuta-SwingUp-Direct-v0 --num-envs 1024 --physics-hz 4000 --max-iterations 600 --accel-bound 60 --pendulum-rate-weight -0.0096 --gamma 0.999 --episode-length-s 10 --episode-jitter 0.2 --no-value-clip --max-rotor-rad 3.1416 --travel-weight -5.0 --rotor-rate-weight -0.1 --rotor-travel-deadband 0.5 --action-rate-weight -1.0 --seed 2 --init-from-actor $actor --run-name tame-e-seed2"
RunStep 'tame07r-tame-e-seed2-eval' ("$score --seed 2 " + '--checkpoint logs/rsl_rl/furuta_swingup/tame-e-seed2/model_599.pt --out results/tame07r_tame-e-seed2.csv')
RunStep 'tame07r-tame-e-seed2-trace' 'scripts/record_swingup_trace.py --headless --physics-hz 4000 --accel-bound 60 --checkpoint logs/rsl_rl/furuta_swingup/tame-e-seed2/model_599.pt --out traces/tame07r_tame-e-seed2.csv'

RunStep 'tame07r-tame-e-seed3' "scripts/train.py --headless --task Furuta-SwingUp-Direct-v0 --num-envs 1024 --physics-hz 4000 --max-iterations 600 --accel-bound 60 --pendulum-rate-weight -0.0096 --gamma 0.999 --episode-length-s 10 --episode-jitter 0.2 --no-value-clip --max-rotor-rad 3.1416 --travel-weight -5.0 --rotor-rate-weight -0.1 --rotor-travel-deadband 0.5 --action-rate-weight -1.0 --seed 3 --init-from-actor $actor --run-name tame-e-seed3"
RunStep 'tame07r-tame-e-seed3-eval' ("$score --seed 3 " + '--checkpoint logs/rsl_rl/furuta_swingup/tame-e-seed3/model_599.pt --out results/tame07r_tame-e-seed3.csv')
RunStep 'tame07r-tame-e-seed3-trace' 'scripts/record_swingup_trace.py --headless --physics-hz 4000 --accel-bound 60 --checkpoint logs/rsl_rl/furuta_swingup/tame-e-seed3/model_599.pt --out traces/tame07r_tame-e-seed3.csv'

Status 'TAME07R3 DONE'
