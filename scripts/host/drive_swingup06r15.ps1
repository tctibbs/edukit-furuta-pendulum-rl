# Run 9: run 5's configuration on the corrected plant. The drive
# target now walks across the control period's substeps instead of stepping once per
# period (FurutaEnvCfg.rotor_target_interpolation, on by default since ADR-0006); with the
# stepped target the articulation gave the 2026-09-10 bench rotor motion 13.0 rad/s through
# the bottom after the first stroke against the machine's 10.3, and with the walked target
# 9.6 at 2, 4 and 16 kHz alike. Same reward, same start, same seed as run 5; a from-rest
# trace follows the gate. Progress in runlogs\swingup06r15-status.log.
$py = "$env:USERPROFILE\Code\isaac\.venv\Scripts\python.exe"
$d = "$env:USERPROFILE\Code\isaac\furuta"
$log = "$d\runlogs\swingup06r15-status.log"
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
          '--num-envs 1024 --physics-hz 4000 --seed 1 --max-iterations 600 ' +
          '--accel-bound 60 --max-rotor-rad 3.1416 ' +
          '--rotor-travel-deadband 0.5 --travel-weight -0.5 --rotor-rate-weight -0.01 ' +
          '--action-rate-weight -0.5 --pendulum-rate-weight -0.0096 ' +
          '--gamma 0.999 --episode-length-s 10 --episode-jitter 0.2 --no-value-clip'
$score = 'scripts/evaluate_swingup.py --headless --physics-hz 4000 --accel-bound 60 ' +
         '--num-envs 256 --seed 1'
$actor = 'logs/rsl_rl/furuta_balance_momentum/ar0p5/model_299.pt'

RunStep 'sw06r-r7-smooth' "$common --init-from-actor $actor --run-name r7-smooth"
RunStep 'sw06r-r7-smooth-eval' ("$score " +
  '--checkpoint logs/rsl_rl/furuta_swingup/r7-smooth/model_599.pt --out results/sw06r_r7_smooth.csv')

RunStep 'sw06r-trace-smooth' 'scripts/record_swingup_trace.py --headless --physics-hz 4000 --accel-bound 60 --checkpoint logs/rsl_rl/furuta_swingup/r7-smooth/model_599.pt --out traces/sw06r_r7_smooth.csv'

Status 'SWINGUP06R15 DONE'
