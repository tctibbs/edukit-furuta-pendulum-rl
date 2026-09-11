# The third bench session's capture replayed through the corrected plant. The session ran the corrected
# plant's own policy, so the replay is the plant's prediction of a trajectory the plant
# itself shaped. Progress in runlogs\swingup06r19-status.log.
$py = "$env:USERPROFILE\Code\isaac\.venv\Scripts\python.exe"
$d = "$env:USERPROFILE\Code\isaac\furuta"
$log = "$d\runlogs\swingup06r19-status.log"
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

$replay = 'scripts/replay_trace.py --headless --plant after --physics-hz 4000 ' +
          '--trace docs/experiments/06-swing-up/hardware/rl_swingup_20260911_replay_input.tsv'
RunStep 'sw06r-session3-replay-0' "$replay --run 0 --out results/sw06r_session3_replay_run0.csv"
RunStep 'sw06r-session3-replay-1' "$replay --run 1 --out results/sw06r_session3_replay_run1.csv"

Status 'SWINGUP06R19 DONE'
