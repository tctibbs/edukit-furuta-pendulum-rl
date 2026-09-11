# The warm-start half of rung 1, rerun, and the two checks the arm-rate sizing added.
#
# drive_swingup06r.ps1 ran the two existence proofs and then lost its r1-warm step to a
# loader defect; the step printed a traceback and exited 0, the driver believed the code,
# scored a checkpoint that did not exist, and moved on to r1-scratch. That run is valid.
# This driver reruns r1-warm with the loader fixed, scores it, then runs the kick
# pump proof (the firmware's swing-up idea on the acceleration path, arm never past
# 0.4 rad or 4.8 rad/s on paper) and a60d replayed through the firmware swing-up with its
# command squashed by tanh, which is how the swing-up task drives it from r1-warm's first
# step. RunStep now reads each step's log for a traceback, since the exit code lies.
# Progress in runlogs\swingup06r3-status.log.
$py = "$env:USERPROFILE\Code\isaac\.venv\Scripts\python.exe"
$d = "$env:USERPROFILE\Code\isaac\furuta"
$log = "$d\runlogs\swingup06r3-status.log"
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
          '--gamma 0.999 --episode-length-s 10 --no-value-clip'
$score = 'scripts/evaluate_swingup.py --headless --physics-hz 4000 --accel-bound 60 ' +
         '--num-envs 256 --seed 1'
$actor = 'logs/rsl_rl/furuta_balance_momentum/ar0p5/model_299.pt'

# The control reached vertical in 236 of 256 from-rest episodes at a median 2.59 s and
# held none; its from-rest trace (traces\sw06r_r1_scratch.csv, recorded 11:08) shows a
# steady rotation over the top. Its iteration-300 checkpoint, the save nearest the
# capture peak the log shows at 340, is scored beside the last. rsl_rl saves at
# multiples of 100 and the final iteration only; there is no model_399.
$ckpt300 = 'logs/rsl_rl/furuta_swingup/r1-scratch/model_300.pt'
if (Test-Path "$d\$($ckpt300 -replace '/', '\')") {
  RunStep 'sw06r-r1-scratch-eval-300' "$score --checkpoint $ckpt300 --out results/sw06r_r1_scratch_300.csv"
} else { Status "skip: $ckpt300 not found" }

RunStep 'sw06r-r1-warm' "$common --init-from-actor $actor --run-name r1-warm"
RunStep 'sw06r-r1-warm-eval' ("$score " +
  '--checkpoint logs/rsl_rl/furuta_swingup/r1-warm/model_599.pt --out results/sw06r_r1_warm.csv')

$proof = 'scripts/scripted_swingup.py --headless --physics-hz 4000 --num-envs 256 --seed 1 ' +
         "--duration-s 30 --checkpoint $actor --policy-bound 60 " +
         '--policy-task Furuta-Balance-Momentum-Direct-Play-v0'
RunStep 'sw06r-proof-kick' ("$proof --pump kick --accel-bound 60 --catch-mode 5.15 --catch-tilt 0.35 " +
  '--out results/sw06r_proof_kick.csv --episodes-out results/sw06r_proof_kick_episodes.csv ' +
  '--trace results/sw06r_proof_kick_trace.csv')
RunStep 'sw06r-a60d-tanh' ("$proof --pump firmware --catch-squash " +
  '--out results/sw06r_a60d_tanh.csv --episodes-out results/sw06r_a60d_tanh_episodes.csv')

Status 'SWINGUP06R3 DONE'
