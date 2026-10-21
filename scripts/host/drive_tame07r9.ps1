# tame07r9. tame-f trained on seeds 1 and 2 as the first stage of tame-k (tame07r8) and was
# never scored on its own, so the ladder's tame-f row carried seed 3 alone. This scores
# both at the benchmark, the same evaluation tame07r5 gave tame-f seed 3.
# Progress in runlogs\tame07r9-status.log.
$py = "$env:USERPROFILE\Code\isaac\.venv\Scripts\python.exe"
$d = "$env:USERPROFILE\Code\isaac\furuta"
$log = "$d\runlogs\tame07r9-status.log"
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

$score = 'scripts/evaluate_swingup.py --headless --physics-hz 4000 --accel-bound 60 --num-envs 256'
$runs = 'logs/rsl_rl/furuta_swingup'

foreach ($tameSeed in 1, 2) {
  RequireFile "$runs/tame-f-seed$tameSeed/model_399.pt"
  RunStep "tame07r-tame-f-seed$tameSeed-eval" "$score --seed $tameSeed --checkpoint $runs/tame-f-seed$tameSeed/model_399.pt --out results/tame07r_tame-f-seed$tameSeed.csv"
  RequireFile "results/tame07r_tame-f-seed$tameSeed.csv"
}

Status 'TAME07R9 DONE'
