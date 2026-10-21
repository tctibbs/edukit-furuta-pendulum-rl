# tame07r6, the tame ladder's decision step on seed 3. Both tame07r5 variants swing up
# on every start (256 of 256) but stay faster than the tame benchmark: tame-f, straight to the
# tame charges, peaks at 2.04 rad and 10.4 rad/s against 1.50 and 8.0; the staged tame-g
# at 2.25 and 11.0. The ladder's rule for "holds but is not tame" is 200 more iterations
# at the tame charges, from the tamer of the two.
# Progress in runlogs\tame07r6-status.log.
$py = "$env:USERPROFILE\Code\isaac\.venv\Scripts\python.exe"
$d = "$env:USERPROFILE\Code\isaac\furuta"
$log = "$d\runlogs\tame07r6-status.log"
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

# drive_tame07r5.ps1's configuration and tame charges.
$common = 'scripts/train.py --headless --task Furuta-SwingUp-Direct-v0 ' +
          '--num-envs 1024 --physics-hz 4000 ' +
          '--accel-bound 60 --max-rotor-rad 3.1416 --rotor-travel-deadband 0.5 ' +
          '--pendulum-rate-weight -0.0096 ' +
          '--gamma 0.999 --episode-length-s 10 --episode-jitter 0.2 --no-value-clip'
$tame = '--travel-weight -5.0 --rotor-rate-weight -0.1 --action-rate-weight -1.0'
$score = 'scripts/evaluate_swingup.py --headless --physics-hz 4000 --accel-bound 60 ' +
         '--num-envs 256 --seed 3'
$warm = 'logs/rsl_rl/furuta_swingup/tame-f-seed3/model_399.pt'
RequireFile $warm

RunStep 'tame07r-tame-h-seed3' "$common $tame --max-iterations 200 --seed 3 --init-from $warm --run-name tame-h-seed3"
RequireFile 'logs/rsl_rl/furuta_swingup/tame-h-seed3/model_199.pt'
RunStep 'tame07r-tame-h-seed3-eval' "$score --checkpoint logs/rsl_rl/furuta_swingup/tame-h-seed3/model_199.pt --out results/tame07r_tame-h-seed3.csv"

Status 'TAME07R6 DONE'
