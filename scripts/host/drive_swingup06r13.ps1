# The bench replay of 2026-09-10 again at higher physics rates, to see whether the PhysX
# articulation's surplus response at 10 rad/s of arm speed is numerical.
# Progress in runlogs\swingup06r13-status.log.
$py = "$env:USERPROFILE\Code\isaac\.venv\Scripts\python.exe"
$d = "$env:USERPROFILE\Code\isaac\furuta"
$log = "$d\runlogs\swingup06r13-status.log"
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
  if (Select-String -Path $stepLog -SimpleMatch 'Traceback (most recent call last)' -Quiet) {
    Status "aborted: $stepName wrote a traceback"; exit 1
  }
}

& "$d\scripts\host\preflight.ps1" -Clear
if ($LASTEXITCODE -ne 0) { Status 'aborted: gpu busy'; exit 1 }

# The 4 kHz replay of attempt 1 gave the simulated pendulum 1.6 times the energy the real one
# took from the first stroke, while the planar model with the arm-rate term reproduces the
# bench to 6.3 degrees rms from the same rotor motion. If the articulation converges toward
# the bench and the planar model as the substep shrinks, the surplus is the solver at high
# joint speed (experiment 04 found the rate mattered by 23 degrees between 1 and 4 kHz); if it
# does not, it is the articulation's own structure.
$replay = 'scripts/replay_trace.py --headless --plant after --stepped-rotor ' +
          '--trace docs/experiments/06-swing-up/hardware/rl_swingup_20260910_replay_input.tsv --run 0'
RunStep 'sw06r-bench-replay-8k' "$replay --physics-hz 8000 --out results/sw06r_bench_replay_run0_8k.csv"
RunStep 'sw06r-bench-replay-16k' "$replay --physics-hz 16000 --out results/sw06r_bench_replay_run0_16k.csv"
RunStep 'sw06r-bench-replay-2k' "$replay --physics-hz 2000 --out results/sw06r_bench_replay_run0_2k.csv"

# The arm-speed rung's policy from rest, per step, so its arrival arm state can be read
# against the catch map before it goes to the bench.
RunStep 'sw06r-trace-armspeed' 'scripts/record_swingup_trace.py --headless --physics-hz 4000 --accel-bound 60 --checkpoint logs/rsl_rl/furuta_swingup/r6-armspeed/model_599.pt --out traces/sw06r_r6_armspeed.csv'

Status 'SWINGUP06R13 DONE'
