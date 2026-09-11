# Swing-up on the reconciled plant, built on the balance policy that holds the
# real pendulum (experiment 05's a60d: 60 rad/s^2, momentum resets, the hold charges it
# ended on). Everything here is that configuration unless a swing-up reason says
# otherwise: the swing-up terms (cosine height, energy shaping, capture well, the gated
# rate charge scaled to the bound), 4 kHz physics because the task pumps, and the
# near-vertical reset share drawn across the recoverable set with the arm moving.
# The trainer now starts environments at random points of their episodes.
#
# First an existence proof, twenty minutes: two scripted governed pumps at 60 rad/s^2
# handing over to a60d inside its own recoverable set, through the policy's
# observations. No controller has been shown to arrive at 60 in acceleration space; the
# planar model says the bang-bang pump overshoots above 25 and the energy-regulated one
# lands. If neither arrives, the learner is being asked for something nothing has done,
# and the ladder starts elsewhere.
#
# Then two runs, one change between them. r1-warm starts from a60d's actor and nothing
# else; r1-scratch starts from random weights. Same seed, same everything. If only the
# warm start arrives, the hold was the missing half; if neither does, the pump is the
# wall and the warm start was not the lever. Each scored at its final checkpoint.
#
# Progress in runlogs\swingup06r-status.log.
$py = "$env:USERPROFILE\Code\isaac\.venv\Scripts\python.exe"
$d = "$env:USERPROFILE\Code\isaac\furuta"
$log = "$d\runlogs\swingup06r-status.log"
$env:OMNI_KIT_ACCEPT_EULA = 'YES'
$env:PYTHONPATH = "$d\src"

function Status($m) { Add-Content -Path $log -Value ((Get-Date -Format s) + ' ' + $m) }

function RunStep($stepName, $argstr) {
  Status "start $stepName"
  $cmd = "/c $py -u $argstr > $d\runlogs\$stepName.log 2>&1"
  $proc = Start-Process -PassThru -Wait -FilePath 'cmd.exe' -ArgumentList $cmd `
    -WorkingDirectory $d -WindowStyle Hidden
  Status "done $stepName exit=$($proc.ExitCode)"
  if ($proc.ExitCode -ne 0) { Status "aborted: $stepName failed"; exit 1 }
}

& "$d\scripts\host\preflight.ps1" -Clear
if ($LASTEXITCODE -ne 0) { Status 'aborted: gpu busy'; exit 1 }

# a60d's trainer and hold charges, plus the swing-up's own settings.
$common = 'scripts/train.py --headless --task Furuta-SwingUp-Direct-v0 ' +
          '--num-envs 1024 --physics-hz 4000 --seed 1 --max-iterations 600 ' +
          '--accel-bound 60 --max-rotor-rad 3.1416 ' +
          '--rotor-travel-deadband 0.5 --travel-weight -0.5 --rotor-rate-weight -0.01 ' +
          '--action-rate-weight -0.5 --pendulum-rate-weight -0.0096 ' +
          '--gamma 0.999 --episode-length-s 10 --no-value-clip'
$score = 'scripts/evaluate_swingup.py --headless --physics-hz 4000 --accel-bound 60 ' +
         '--num-envs 256 --seed 1'
# ar0p5 is a60d's run name on the host; the committed copy is docs/experiments/05-balance/checkpoints/momentum_a60d_seed1_model_299.pt.
$actor = 'logs/rsl_rl/furuta_balance_momentum/ar0p5/model_299.pt'

# Existence proof. Pump and environment at 60, the catch handed to a60d inside the
# 60 rad/s^2 set (5.15 rad/s of unstable mode, 0.35 rad of tilt), governor allowance
# 2 rad, 30 s, from the task's hanging spread. Two laws: the bang-bang pump, which the
# planar model says overshoots the set at 60, and the energy-regulated pump at gain 8,
# which it says lands in 1.3 s at 0.63 rad/s of mode (planar_sizing.csv).
$proof = 'scripts/scripted_swingup.py --headless --physics-hz 4000 --num-envs 256 --seed 1 ' +
         '--duration-s 30 --accel-bound 60 --policy-bound 60 --catch-mode 5.15 ' +
         "--catch-tilt 0.35 --allowance 2.0 --checkpoint $actor " +
         '--policy-task Furuta-Balance-Momentum-Direct-Play-v0'
# One summary file per law: the energy law's row carries two extra columns, and the
# script refuses to append a row whose header differs from the file's.
RunStep 'sw06r-proof-bangbang' ("$proof --pump textbook --out results/sw06r_proof_bangbang.csv " +
  '--episodes-out results/sw06r_proof_bangbang_episodes.csv ' +
  '--trace results/sw06r_proof_bangbang_trace.csv')
RunStep 'sw06r-proof-energy8' ("$proof --pump energy --pump-gain 8 --out results/sw06r_proof_energy8.csv " +
  '--episodes-out results/sw06r_proof_energy8_episodes.csv ' +
  '--trace results/sw06r_proof_energy8_trace.csv')

RunStep 'sw06r-r1-warm' "$common --init-from-actor $actor --run-name r1-warm"
RunStep 'sw06r-r1-warm-eval' ("$score " +
  '--checkpoint logs/rsl_rl/furuta_swingup/r1-warm/model_599.pt --out results/sw06r_r1_warm.csv')

RunStep 'sw06r-r1-scratch' "$common --run-name r1-scratch"
RunStep 'sw06r-r1-scratch-eval' ("$score " +
  '--checkpoint logs/rsl_rl/furuta_swingup/r1-scratch/model_599.pt --out results/sw06r_r1_scratch.csv')

Status 'SWINGUP06R DONE'
