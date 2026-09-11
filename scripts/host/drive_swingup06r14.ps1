# The bench replay with the rotor target walked across the substeps instead of stepped,
# at 2, 4 and 16 kHz, against the stepped runs already on disk.
# Progress in runlogs\swingup06r14-status.log.
$py = "$env:USERPROFILE\Code\isaac\.venv\Scripts\python.exe"
$d = "$env:USERPROFILE\Code\isaac\furuta"
$log = "$d\runlogs\swingup06r14-status.log"
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

# The stepped target gave the articulation 13.0 rad/s through the bottom after the first
# stroke at 4 kHz and more at every finer rate, against the machine's 10.3 and the planar
# model's 8.9. If the interpolated target lands near the bench at all three rates, the plant
# defect is found and every policy trains again on the corrected plant.
$replay = 'scripts/replay_trace.py --headless --plant after ' +
          '--trace docs/experiments/06-swing-up/hardware/rl_swingup_20260910_replay_input.tsv --run 0'
RunStep 'sw06r-bench-replay-smooth-4k' "$replay --physics-hz 4000 --out results/sw06r_bench_replay_run0_smooth_4k.csv"
RunStep 'sw06r-bench-replay-smooth-16k' "$replay --physics-hz 16000 --out results/sw06r_bench_replay_run0_smooth_16k.csv"
RunStep 'sw06r-bench-replay-smooth-2k' "$replay --physics-hz 2000 --out results/sw06r_bench_replay_run0_smooth_2k.csv"

Status 'SWINGUP06R14 DONE'
