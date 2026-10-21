# tame07r7, seed 3. tame-f's training log shows the arm charges flat from iteration
# 50 to 399 (travel -0.19 to -0.63 per step, arm rate -0.22 to -0.42) against a capture
# reward near 1.7, with the width steady at 0.35: the policy had settled on a swing-up
# those charges price as cheap, so more iterations at the same charges (tame07r6,
# tame-h) are not expected to tame it. The swing-up is a second or two of a 10 s episode,
# which dilutes any per-step charge on its strokes. Two ways to make the strokes
# expensive, each 300 iterations from tame-f:
#   tame-i  the arm bound itself as the termination (1.5 rad, the benchmark's limit) and the
#           arm-rate charge four times tame's
#   tame-j  no bound, the travel charge doubled and the arm-rate charge four times tame's
# Waits for tame07r6's evaluation row before touching the GPU.
# Progress in runlogs\tame07r7-status.log.
$py = "$env:USERPROFILE\Code\isaac\.venv\Scripts\python.exe"
$d = "$env:USERPROFILE\Code\isaac\furuta"
$log = "$d\runlogs\tame07r7-status.log"
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

# Wait on tame07r6's artifact, not its status line.
Status 'waiting for results/tame07r_tame-h-seed3.csv'
$deadline = (Get-Date).AddMinutes(90)
while (-not (Test-Path "$d\results\tame07r_tame-h-seed3.csv")) {
  if (Select-String -Path "$d\runlogs\tame07r6-status.log" -SimpleMatch 'aborted' -Quiet) {
    Status 'aborted: tame07r6 aborted'; exit 1
  }
  if ((Get-Date) -gt $deadline) { Status 'aborted: tame07r6 evaluation row never landed'; exit 1 }
  Start-Sleep -Seconds 30
}

# The evaluation process can take a minute to release the GPU after writing its row.
$free = $false
for ($attempt = 0; $attempt -lt 10; $attempt++) {
  & "$d\scripts\host\preflight.ps1" -Clear
  if ($LASTEXITCODE -eq 0) { $free = $true; break }
  Start-Sleep -Seconds 30
}
if (-not $free) { Status 'aborted: gpu busy'; exit 1 }

$common = 'scripts/train.py --headless --task Furuta-SwingUp-Direct-v0 ' +
          '--num-envs 1024 --physics-hz 4000 --accel-bound 60 --rotor-travel-deadband 0.5 ' +
          '--pendulum-rate-weight -0.0096 ' +
          '--gamma 0.999 --episode-length-s 10 --episode-jitter 0.2 --no-value-clip'
$score = 'scripts/evaluate_swingup.py --headless --physics-hz 4000 --accel-bound 60 ' +
         '--num-envs 256 --seed 3'
$warm = 'logs/rsl_rl/furuta_swingup/tame-f-seed3/model_399.pt'
RequireFile $warm

RunStep 'tame07r-tame-i-seed3' "$common --max-rotor-rad 1.5 --travel-weight -5.0 --rotor-rate-weight -0.4 --action-rate-weight -1.0 --max-iterations 300 --seed 3 --init-from $warm --run-name tame-i-seed3"
RequireFile 'logs/rsl_rl/furuta_swingup/tame-i-seed3/model_299.pt'
RunStep 'tame07r-tame-i-seed3-eval' "$score --checkpoint logs/rsl_rl/furuta_swingup/tame-i-seed3/model_299.pt --out results/tame07r_tame-i-seed3.csv"

RunStep 'tame07r-tame-j-seed3' "$common --max-rotor-rad 3.1416 --travel-weight -10.0 --rotor-rate-weight -0.4 --action-rate-weight -1.0 --max-iterations 300 --seed 3 --init-from $warm --run-name tame-j-seed3"
RequireFile 'logs/rsl_rl/furuta_swingup/tame-j-seed3/model_299.pt'
RunStep 'tame07r-tame-j-seed3-eval' "$score --checkpoint logs/rsl_rl/furuta_swingup/tame-j-seed3/model_299.pt --out results/tame07r_tame-j-seed3.csv"

Status 'TAME07R7 DONE'
