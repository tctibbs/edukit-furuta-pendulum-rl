# The governor rung: rung 1's warm configuration plus a price on the arm's projected
# overrun, the term the environment has carried at zero weight from the start.
#
# Seed 2 of rung 1 holds every episode whose opening stroke stays inside the travel bound
# and loses 115 of 256 to that stroke running the arm through pi at a median 0.45 s, before
# the pendulum has left the bottom. The travel charge starts 0.5 rad out and the bound
# itself is the first hard word the opening hears. Because the training's exploration
# noise dithered the same opening short of the bound, the mean action deployed at the
# gate is sharper than any stroke the policy paid for. The governor term charges the
# squared distance by which the arm's stopping point, at full braking from where it is
# and how fast it is turning, would pass 2.2 rad, every step. An opening that will
# overrun is billed as it is thrown. This run is one change from r1-warm.
# Progress in runlogs\swingup06r7-status.log.
$py = "$env:USERPROFILE\Code\isaac\.venv\Scripts\python.exe"
$d = "$env:USERPROFILE\Code\isaac\furuta"
$log = "$d\runlogs\swingup06r7-status.log"
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
          '--gamma 0.999 --episode-length-s 10 --governor-weight -0.5 --governor-margin 2.2 --no-value-clip'
$score = 'scripts/evaluate_swingup.py --headless --physics-hz 4000 --accel-bound 60 ' +
         '--num-envs 256 --seed 1'
$actor = 'logs/rsl_rl/furuta_balance_momentum/ar0p5/model_299.pt'

RunStep 'sw06r-r4-governor' "$common --init-from-actor $actor --run-name r4-governor"
RunStep 'sw06r-r4-governor-eval' ("$score " +
  '--checkpoint logs/rsl_rl/furuta_swingup/r4-governor/model_599.pt --out results/sw06r_r4_governor.csv')

Status 'SWINGUP06R7 DONE'
