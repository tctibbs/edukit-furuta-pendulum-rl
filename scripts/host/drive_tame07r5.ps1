# tame07r5, the tame ladder's first rung, on seed 3 (the hardest start). tame-e's charges
# learned a swing-up from the balance actor on seed 1 only: the command-change charge
# collapsed the exploration width to 0.15-0.19 by iteration 500 on every seed, before seeds
# 2 and 3 had learned the catch. So this starts from a swing-up that already works, the
# corrected-plant r7-smooth checkpoint, with its critic, width and optimizer (--init-from),
# and fine-tunes it under the tame charges. (a) straight to the tame charges for 400
# iterations. (b) 150 iterations at the geometric midpoint of the r7 and tame charges, then
# 250 at the tame charges; the same 400 in total.
# Progress in runlogs\tame07r5-status.log.
$py = "$env:USERPROFILE\Code\isaac\.venv\Scripts\python.exe"
$d = "$env:USERPROFILE\Code\isaac\furuta"
$log = "$d\runlogs\tame07r5-status.log"
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

# r7-smooth's configuration (drive_swingup06r17.ps1) with its three arm charges taken out.
$common = 'scripts/train.py --headless --task Furuta-SwingUp-Direct-v0 ' +
          '--num-envs 1024 --physics-hz 4000 ' +
          '--accel-bound 60 --max-rotor-rad 3.1416 --rotor-travel-deadband 0.5 ' +
          '--pendulum-rate-weight -0.0096 ' +
          '--gamma 0.999 --episode-length-s 10 --episode-jitter 0.2 --no-value-clip'
$tame = '--travel-weight -5.0 --rotor-rate-weight -0.1 --action-rate-weight -1.0'
$mid = '--travel-weight -1.6 --rotor-rate-weight -0.032 --action-rate-weight -0.7'
$score = 'scripts/evaluate_swingup.py --headless --physics-hz 4000 --accel-bound 60 ' +
         '--num-envs 256 --seed 3'
$warm = 'logs/rsl_rl/furuta_swingup/r7-smooth-seed3/model_599.pt'
RequireFile $warm

RunStep 'tame07r-tame-f-seed3' "$common $tame --max-iterations 400 --seed 3 --init-from $warm --run-name tame-f-seed3"
RequireFile 'logs/rsl_rl/furuta_swingup/tame-f-seed3/model_399.pt'
RunStep 'tame07r-tame-f-seed3-eval' "$score --checkpoint logs/rsl_rl/furuta_swingup/tame-f-seed3/model_399.pt --out results/tame07r_tame-f-seed3.csv"

RunStep 'tame07r-tame-g-mid-seed3' "$common $mid --max-iterations 150 --seed 3 --init-from $warm --run-name tame-g-mid-seed3"
RequireFile 'logs/rsl_rl/furuta_swingup/tame-g-mid-seed3/model_149.pt'
RunStep 'tame07r-tame-g-seed3' "$common $tame --max-iterations 250 --seed 3 --init-from logs/rsl_rl/furuta_swingup/tame-g-mid-seed3/model_149.pt --run-name tame-g-seed3"
RequireFile 'logs/rsl_rl/furuta_swingup/tame-g-seed3/model_249.pt'
RunStep 'tame07r-tame-g-seed3-eval' "$score --checkpoint logs/rsl_rl/furuta_swingup/tame-g-seed3/model_249.pt --out results/tame07r_tame-g-seed3.csv"

Status 'TAME07R5 DONE'
