# Run 7: run 5's configuration with excess energy priced fourfold.
# The symmetric energy term pays 1.52 of 2.0 at 1.24 times the separatrix energy, and the
# first bench run showed the trap live: after a missed catch the pendulum went round at
# 1.0 to 1.1 times the separatrix speed for 7 and 11 s while the policy kept pumping it.
# --energy-excess-gain 4 charges energy above the separatrix four times harder than
# energy below it. Pumping past the top then costs more than it earns.
# One change against run 5.
# Progress in runlogs\swingup06r10-status.log.
$py = "$env:USERPROFILE\Code\isaac\.venv\Scripts\python.exe"
$d = "$env:USERPROFILE\Code\isaac\furuta"
$log = "$d\runlogs\swingup06r10-status.log"
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
          '--action-rate-weight -0.5 --energy-excess-gain 4 --pendulum-rate-weight -0.0096 ' +
          '--gamma 0.999 --episode-length-s 10 --episode-jitter 0.2 --no-value-clip'
$score = 'scripts/evaluate_swingup.py --headless --physics-hz 4000 --accel-bound 60 ' +
         '--num-envs 256 --seed 1'
$actor = 'logs/rsl_rl/furuta_balance_momentum/ar0p5/model_299.pt'

RunStep 'sw06r-r5-energy' "$common --init-from-actor $actor --run-name r5-energy"
RunStep 'sw06r-r5-energy-eval' ("$score " +
  '--checkpoint logs/rsl_rl/furuta_swingup/r5-energy/model_599.pt --out results/sw06r_r5_energy.csv')

Status 'SWINGUP06R10 DONE'
