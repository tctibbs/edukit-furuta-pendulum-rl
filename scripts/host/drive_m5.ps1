# Experiment 05 on the reconciled plant: the same ladder the first pass walked, so every
# lesson it drew is re-tested rather than assumed. Runs serially; progress in
# runlogs\m5-status.log.
# Both paths are the host's own. Pass them in, or set the defaults below to match the
# layout in docs/runbooks/training-host-setup.md.
param(
  [string]$Python = "$PSScriptRoot\..\..\..\.venv\Scripts\python.exe",
  [string]$Checkout = "$PSScriptRoot\..\.."
)
$py  = (Resolve-Path $Python).Path
$d   = (Resolve-Path $Checkout).Path
$log = "$d\runlogs\m5-status.log"
$env:OMNI_KIT_ACCEPT_EULA = 'YES'
$env:PYTHONPATH = "$d\src"
function Status($m) { Add-Content -Path $log -Value ((Get-Date -Format s) + ' ' + $m) }
function RunStep($name, $argstr) {
  Status "start $name"
  $cmd = "/c $py -u $argstr > $d\runlogs\$name.log 2>&1"
  $p = Start-Process -PassThru -Wait -FilePath 'cmd.exe' -ArgumentList $cmd -WorkingDirectory $d -WindowStyle Hidden
  Status "done $name exit=$($p.ExitCode)"
}

& "$d\scripts\host\preflight.ps1" -Clear
if ($LASTEXITCODE -ne 0) { Status 'aborted: gpu busy'; exit 1 }

# The first pass's checkpoints and evaluations move aside rather than being overwritten,
# so the redo writes to the canonical names and nothing is lost.
$old = "$d\logs\rsl_rl\furuta_balance"
if ((Test-Path $old) -and -not (Test-Path "$old`_pre_reconciliation")) {
  Move-Item $old "$old`_pre_reconciliation"
  Status 'moved first-pass checkpoints to furuta_balance_pre_reconciliation'
}
New-Item -ItemType Directory -Force -Path "$d\results\pre_reconciliation" | Out-Null
Get-ChildItem "$d\results\eval_seed*.csv" -ErrorAction SilentlyContinue | Move-Item -Destination "$d\results\pre_reconciliation" -Force

Status 'm5 redo started'
$T = 'scripts/train.py --headless --num-envs 1024'

# The ladder. Budgets match the first pass, so "does it still fail" is a fair question.
RunStep 'run2-cosine'   "$T --max-iterations 33 --seed 1 --upright-reward cosine --run-name run2-cosine"
RunStep 'run4-lownoise' "$T --max-iterations 56 --seed 1 --init-noise-std 0.3 --run-name run4-lownoise"
foreach ($s in 1..5) {
  RunStep "seed$s" "$T --max-iterations 300 --seed $s --run-name seed$s"
}

# Evaluation, the first pass's protocol: seed 1 on the fine kick grid, the rest coarse.
$E = 'scripts/evaluate.py --headless'
RunStep 'eval-seed1' "$E --checkpoint logs/rsl_rl/furuta_balance/seed1/model_299.pt --seed 101 --out results/eval_seed1.csv"
foreach ($s in 2..5) {
  RunStep "eval-seed$s" "$E --checkpoint logs/rsl_rl/furuta_balance/seed$s/model_299.pt --seed 10$s --kicks 0,0.2,0.4,0.6,0.8,1.0 --out results/eval_seed$s.csv"
}

# The write-up's clips.
RunStep 'rec-untrained' 'scripts/record_policy.py --headless --num-envs 9 --steps 1500 --output videos/m5untrained'
RunStep 'rec-trained'   'scripts/record_policy.py --headless --num-envs 9 --steps 1500 --output videos/m5trained --checkpoint logs/rsl_rl/furuta_balance/seed1/model_299.pt'
Status 'M5 DONE'
