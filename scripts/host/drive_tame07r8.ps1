# tame07r8. Seed 3's two stronger variants each miss the tame benchmark by a hair, on
# different limits: tame-i (arm bound 1.5 rad, arm-rate charge -0.4) peaks at 1.15 rad
# but 8.2 rad/s; tame-j (travel charge -10, arm-rate -0.4, no bound) peaks at 6.3 rad/s
# but 1.52 rad. tame-k takes both, the 1.5 rad bound and the -10 travel charge with -0.4
# on arm rate, for 300 iterations from tame-f. The same two-stage recipe, 400 iterations
# at tame-e's charges from r7-smooth and then 300 as tame-k, runs on seeds 2 and 1 behind
# it, queued now so the decision on seed 3 does not leave the GPU idle.
# Progress in runlogs\tame07r8-status.log.
$py = "$env:USERPROFILE\Code\isaac\.venv\Scripts\python.exe"
$d = "$env:USERPROFILE\Code\isaac\furuta"
$log = "$d\runlogs\tame07r8-status.log"
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

function RequireFile($path) {
  if (-not (Test-Path "$d\$path")) { Status "aborted: missing $path"; exit 1 }
}

& "$d\scripts\host\preflight.ps1" -Clear
if ($LASTEXITCODE -ne 0) { Status 'aborted: gpu busy'; exit 1 }

$common = 'scripts/train.py --headless --task Furuta-SwingUp-Direct-v0 ' +
          '--num-envs 1024 --physics-hz 4000 --accel-bound 60 --rotor-travel-deadband 0.5 ' +
          '--pendulum-rate-weight -0.0096 ' +
          '--gamma 0.999 --episode-length-s 10 --episode-jitter 0.2 --no-value-clip'
$stage1 = '--max-rotor-rad 3.1416 --travel-weight -5.0 --rotor-rate-weight -0.1 --action-rate-weight -1.0 --max-iterations 400'
$stage2 = '--max-rotor-rad 1.5 --travel-weight -10.0 --rotor-rate-weight -0.4 --action-rate-weight -1.0 --max-iterations 300'
$score = 'scripts/evaluate_swingup.py --headless --physics-hz 4000 --accel-bound 60 --num-envs 256'
$runs = 'logs/rsl_rl/furuta_swingup'

# Seed 3: stage 1 already ran as tame-f.
RequireFile "$runs/tame-f-seed3/model_399.pt"
RunStep 'tame07r-tame-k-seed3' "$common $stage2 --seed 3 --init-from $runs/tame-f-seed3/model_399.pt --run-name tame-k-seed3"
RequireFile "$runs/tame-k-seed3/model_299.pt"
RunStep 'tame07r-tame-k-seed3-eval' "$score --seed 3 --checkpoint $runs/tame-k-seed3/model_299.pt --out results/tame07r_tame-k-seed3.csv"

foreach ($seedPair in @(@(2, 'r7-smooth-seed2'), @(1, 'r7-smooth'))) {
  $seedNumber = $seedPair[0]
  $warmRun = $seedPair[1]
  RequireFile "$runs/$warmRun/model_599.pt"
  RunStep "tame07r-tame-f-seed$seedNumber" "$common $stage1 --seed $seedNumber --init-from $runs/$warmRun/model_599.pt --run-name tame-f-seed$seedNumber"
  RequireFile "$runs/tame-f-seed$seedNumber/model_399.pt"
  RunStep "tame07r-tame-k-seed$seedNumber" "$common $stage2 --seed $seedNumber --init-from $runs/tame-f-seed$seedNumber/model_399.pt --run-name tame-k-seed$seedNumber"
  RequireFile "$runs/tame-k-seed$seedNumber/model_299.pt"
  RunStep "tame07r-tame-k-seed$seedNumber-eval" "$score --seed $seedNumber --checkpoint $runs/tame-k-seed$seedNumber/model_299.pt --out results/tame07r_tame-k-seed$seedNumber.csv"
}

Status 'TAME07R8 DONE'
