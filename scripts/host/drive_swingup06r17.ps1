# Run 9 over the seed set: seeds 2 and 3 of run 5's configuration on the
# corrected plant (ADR-0006), each gated at its last checkpoint. Seed 1 alone reads
# 252 of 256 in 1.25 s.
# Progress in runlogs\swingup06r17-status.log.
$py = "$env:USERPROFILE\Code\isaac\.venv\Scripts\python.exe"
$d = "$env:USERPROFILE\Code\isaac\furuta"
$log = "$d\runlogs\swingup06r17-status.log"
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
          '--gamma 0.999 --episode-length-s 10 --episode-jitter 0.2 --no-value-clip'
$score = 'scripts/evaluate_swingup.py --headless --physics-hz 4000 --accel-bound 60 ' +
         '--num-envs 256'
$actor = 'logs/rsl_rl/furuta_balance_momentum/ar0p5/model_299.pt'

RunStep 'sw06r-r7-smooth-seed2' "$common --seed 2 --init-from-actor $actor --run-name r7-smooth-seed2"
RunStep 'sw06r-r7-smooth-seed2-eval' ("$score --seed 2 " +
  '--checkpoint logs/rsl_rl/furuta_swingup/r7-smooth-seed2/model_599.pt --out results/sw06r_r7_smooth_seed2.csv')

RunStep 'sw06r-r7-smooth-seed3' "$common --seed 3 --init-from-actor $actor --run-name r7-smooth-seed3"
RunStep 'sw06r-r7-smooth-seed3-eval' ("$score --seed 3 " +
  '--checkpoint logs/rsl_rl/furuta_swingup/r7-smooth-seed3/model_599.pt --out results/sw06r_r7_smooth_seed3.csv')

Status 'SWINGUP06R17 DONE'
