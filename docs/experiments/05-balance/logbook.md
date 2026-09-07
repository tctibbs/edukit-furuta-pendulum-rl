# Balance training runs

Log of every configuration tried. The reasoning behind the working one is in the [write-up](./writeup.md); this file is the record that the failures happened.

Training host, RTX 5080, torch 2.7.0+cu128, `Furuta-Balance-Direct-v0` on the plant Experiment 04 reconciled, 5000-step episode cap. Mean episode length is the success number. The upright reward column is the term scoring how vertical the pendulum is, which is what run 2 shows to be the wrong shape. Runs went through a host driver calling `scripts/host/preflight.ps1`, which refuses to start while another job holds the GPU, and `scripts/host/drive_m5.ps1` is the first ladder's; a 300 iteration seed took 11 minutes with the machine to itself, and an earlier pass that shared it with an evaluation had run fifteen times slower.

| # | Envs | Upright reward | `init_noise_std` | Iterations | Mean episode length | Outcome |
|---|---|---|---|---|---|---|
| 1 | 4096 | `cos(theta)` | 1.0 | 0 | n/a | Scene never built. 17 min at "Starting the simulation," then killed |
| 2 | 1024 | `cos(theta)` | 1.0 | 32 | 247 to 299 | Negative. No learning |
| 3 | 1024 | `1-(theta/theta_max)^2` | 1.0 | 62 | 247 to 543 | Learning. Noise std rose to 1.23, 55 percent of actions clipped. Read off seed 1's first 62 iterations, not a separate run |
| 4 | 1024 | `1-(theta/theta_max)^2` | 0.3 | 55 | 248 to 280 | Negative. Worse than run 3 |
| 5 | 1024 | `1-(theta/theta_max)^2` | 1.0 | 300 | 2014, at the cap from iteration 177 | Seed 1 of the gate set |
| 6 | 1024 | `1-(theta/theta_max)^2` | 1.0 | 300 | 1755, at the cap from iteration 173 | Seed 2, run 5's configuration unchanged |
| 7 | 1024 | `1-(theta/theta_max)^2` | 1.0 | 300 | 4999, at the cap from iteration 186 | Seed 3, run 5's configuration unchanged |
| 8 | 1024 | `1-(theta/theta_max)^2` | 1.0 | 300 | 4866, peaked at 4866 | Seed 4, run 5's configuration unchanged |
| 9 | 1024 | `1-(theta/theta_max)^2` | 1.0 | 300 | 4976, at the cap from iteration 158 | Seed 5, run 5's configuration unchanged |

**Run 1.** The asset sets `clone_in_fabric=False`, so 4096 articulations clone one at a time. 1024 boots in about a minute.

**Run 2.** `cos` moves 0.058 across the 20 degree envelope against an alive term of 1.0 per step. The slow drift from 247 to 299 is the noise std climbing to 1.17, not the reward teaching anything; the quadratic reaches 413 in the same 32 iterations. Replaced with `1 - (theta/theta_max)^2`.

**Run 3.** At `init_noise_std` 1.0 on a `[-1, 1]` action space, the zero-mean tail outside the rails is 31.7 percent, and more at the learned 1.23. Measured fractions run higher, since the policy mean drifts off zero.

**Run 4.** Cutting the noise to 0.3 took clipping to 2 percent as intended and made learning worse. The wide noise is exploration this plant needs, and the clipping is a symptom.

Between 32 and 55 percent of actions clip for the whole of run 5, and the policy learns anyway. The [write-up](./writeup.md) plots it.

## Evaluation

Seeds 1, 4 and 5 hold every episode; seed 3 holds 254 of 256; seed 2 drifts the arm into the 90 degree travel bound and terminates every episode at every kick. An earlier pass of this experiment on the unreconciled plant had the same one-in-five travel drift, in seed 4, with the other four holding. The failure follows the reward's 0.35 rad travel deadband rather than a seed or the plant's dissipation, and the drifting seed is not the tightest balancer in either pass.

## Evaluation metric, two false starts

Both produced plausible numbers, so both are worth naming.

A terminated episode scored as a **recovery**: the environment resets a fallen pendulum to near upright, and the next step then reads as inside the envelope. The tell was recovery near 1.00 at every kick size while worst rotor travel sat at exactly 1.57 rad, the `pi/2` termination bound.

Scoring on the wrapper's `dones` was worse, since `dones` unions termination with time-out and every episode surviving its full 30 s times out. The tell was hold 0.000 alongside a 1.44 degree peak excursion.

`reset_terminated` excludes time-outs and is what every number in this report uses.

## Handover

The scripted pump handing over to seed 1's checkpoint, 4 kHz physics, 256 episodes from the swing-up task's hanging spread.

**LQR baseline at the configured 11.78 rad/s^2, 40 s.** Zero handovers. Environment 0's trace plateaus at 116.4 degrees from hanging with 12.4 rad/s through the bottom; the governor brakes on 5 percent of steps, so the allowance is not the limit. `results/handover_lqr_4k.csv` and the trace, decimated five to one, are committed as `handover_trace_a11.78.csv`.

**Scoring defect, found by review before the sweep ran.** The loop ran exactly the episode length, and the environment's time-out fires one step before that and resets every environment to hanging, so the last iteration read a hanging pendulum and scored every survivor as leaving the hold window. Every hold number this script had ever produced was zero for that reason. Both loops now place the time-out one second outside the scored window. The preceding baseline is unaffected, since nothing arrived to be scored.

**Half-swing counter.** Counting strict sign changes of the quantized rate missed reversals where the 16-sample slope sat at exactly zero across a small extremum, and double-counted a one-count dither at a peak. The counter now carries the last nonzero sign and requires 0.1 rad of travel since the last counted reversal, and the golden trace is recounted under the same rule: 14 reversals in 8.01 s.

**Planar check.** The reconciled planar model with the same governed pump arrives at 11.78 rad/s^2 in 14.78 s after 26 reversals, and at 15 rad/s^2 in 7.12 s after 13, against the hardware's 8.01 s and 14. It has no rotor-rate terms, so its arrival at 11.78 is not evidence against PhysX's stall. `scripts/scripted_swingup.py` still carries the pre-reconciliation plant (1.07 degree Coulomb, no drag) inline and should read `furuta.planar` instead.

**Pump bound sweep, seed 1's policy, 30 s.** `--accel-bound` raises the pump's and the environment's limit while the policy keeps 11.78. Handovers 236, 109, and 65 of 256 at 15, 20, and 30 rad/s^2; median handover 11.1, 5.0, and 2.2 s after 18, 8, and 4 reversals; the policy holds 16, 14, and 7 of them. Beyond 15 rad/s^2, the pump overshoots the set more often than it lands in it. At 15 the climb tracks the golden trace swing for swing through 7 s, then goes over the top where the hardware arrived. Rows in `handover.csv`, per-episode files `handover_episodes.csv` (15) and `handover_episodes_a20.csv`, `handover_episodes_a30.csv`.

**Where the 15 rad/s^2 handovers fail.** 220 of the 236 handovers are lost; 218 of those end on the 180 degree travel bound and none with the pendulum falling. 227 of the 236 handovers fire at 20 degrees of tilt with the pendulum approaching at about 2 rad/s, the arm a median 1.09 rad off center moving at 0.78 rad/s. Holds concentrate at the fastest arrivals, 24 percent of those exceeding 0.8 rad/s of unstable mode and none below 0.6. The unstable-mode rms at handover is 0.61 rad/s, inside the kick sweep's capacity, so the pendulum's momentum is not what the policy lacks.

**LQR control at 15.** Same 236 handover states to the last digit (the simulation is deterministic across processes with the same seed), LQR clamped to 11.78: holds 168, terminates 60 on travel, 8 leave the envelope late. The arrivals are catchable with the policy's authority. `handover_episodes_lqr.csv`.

**Ledger.** `results/handover.csv` on the host mixes two column sets, because the LQR baseline ran before `accel_bound_rad_s2` existed and the sweep appended to it; the script now refuses to append to a file whose header differs. The committed `handover.csv` is rebuilt from each run's `[gate ]` line.

## Follow-on: resets across the recoverable set

`Furuta-Balance-Momentum-Direct-v0` expands the initial state distribution beyond the upright balance task: tilt across $\pm 0.3$ rad, unstable modal velocity across $\pm 0.9$ rad/s with rate following deterministically, arm displacement up to $\pm 2$ rad at velocities up to $\pm 6$ rad/s, and travel bound $\pi$. Three seeds trained across 1024 environments for 300 iterations at 1 kHz physics rate.

**Seed 1 training.** Reward 196 at iteration 0, 509 at 149, 914 at 199, 6656 at 249 and 6178 at 299, with mean episode length rising from 123 to about 3300 of 5000 steps; the capture is learned late and the curve has not flattened by 300. Iteration time 1.9 to 2.7 s of collection, the machine to itself. Curve in `results_momentum.csv`.

**Seeds 2 and 3 training.** Seed 2 reaches reward 6443 at iteration 199, 7791 at 249, 6729 at 299 (episode length 3313, 4020, 3495 of 5000); seed 3 is slower, 2296 at 199, then 7045 and 7914 at 249 and 299 (1216, 3641, 4059). All three are still climbing or oscillating at 300 iterations under exploration noise.

**Evaluation, first attempt, wrong protocol.** The first pass's `evaluate.py` scores a hold over the whole 30 s episode. Momentum starts begin up to 17 degrees out, so hold rate reads 0.01 to 0.03 by construction; the same loop also ran to the episode time-out, which resets every environment in place, and a reset from a momentum start lands outside 3 degrees, so the last iteration failed every hold as well. That second defect is the one found in `scripted_swingup.py`; the first pass's balance numbers escaped it because a balance reset lands inside 3 degrees. The rows are kept as `recovery_momentum.csv` for what they do say: 26 to 31 percent of momentum starts end on the travel bound, against 0.6 percent that cannot stop inside pi from where they start. The evaluator now takes `--settle-s`, and the re-score with a 2 s settle window is the follow-on's hold number.

**Momentum seed 1 on the 15 rad/s^2 handover.** The same 236 handover states as the first policy and the LQR, identical in every row. Held 166, terminated 62 on travel, 8 left the envelope late. The first policy held 16 of these, all of which the momentum policy also holds. By arm rate at handover: below 1 rad/s the momentum policy holds 90 percent, 1 to 2 rad/s 43 percent, exceeding 2 rad/s 24 percent; by unstable mode it holds 79 percent below 0.6 rad/s, where the first policy held none. Per-episode file `handover_episodes_momentum.csv`, environment 0's trace `handover_trace_momentum.csv`.

**Late handover, `--catch-tilt 0.1`, both policies at 15 rad/s^2.** Handovers 165 of 256, median 13.1 s, the pendulum inside 5.7 degrees approaching at a median 1.4 rad/s, mode rms 0.71, arm 1.23 rad out at 2.55 rad/s. First policy holds 113, terminates 44, leaves late 8; momentum policy holds 123, terminates 34, leaves late 8. Same 165 states in both. The narrower window costs 71 handovers to overshoot. `handover_episodes_late.csv` and `handover_episodes_momentum_late.csv`.

**One-rig recordings.** `--record --num-envs 1` at 4 kHz, the exp-04 camera, both policies from seed 1's draw; the two traces agree to 0.000 degrees for the 17.4 s before the handover at 17.48 s. First policy: reset at 18.67 s. Momentum policy: inside 3 degrees for the whole last 5 s, 0.1 degrees at 24 s. The recorder drew 3034 of 11999 frames on the first run and a clean odd half, 5998, on the second, so the blank pattern is not even stable between two runs of one configuration. `hold_frames_to_gif.py` builds the clips by holding the latest drawn frame at each output instant. The first clip compresses to 1.8 MB against the second's 0.7 MB at identical settings, from the held frames' exposure jitter, which is why the pair is committed as two files rather than one side by side.

**Evaluation, second attempt, `--settle-s 2`.** Hold judged from 2 s to 30 s, time-out outside the window. Momentum seeds 1, 2, 3 from momentum starts: hold 0.719, 0.688, 0.742; terminated 0.281, 0.313, 0.258; peak excursion 9.3 to 9.9 degrees. First policy on the same starts: hold 0.355, terminated 0.641, peak 15.0 degrees. Seed 1's kicks: hold 0.719 at 0.2 and 0.4, 0.680 at 0.6, 0.184 at 0.8, 0 at 1.0; recovery 0.719, 0.719, 0.680, 0.375, 0.074. Every failure is a travel termination. `recovery_momentum.csv` now holds these rows and `recovery_momentum_first_policy.csv` the first policy's; the whole-episode-hold rows from the first attempt were replaced, and the preceding logbook entry is their record.

## The bound from source code and telemetry captures

Read on 2026-09-06 without the desk, from `firmware/` (the extracted stock source with this project's modes) and every capture with a rotor column. The swing-up's kicks are `BSP_MotorControl_Move` calls of 200 microsteps run by the L6474 profile, MIN_SPEED 800, MAX_ACCEL 6000, MAX_SPEED 2000 microsteps/s and /s^2, with the loop blocked in `WaitWhileActive` for the move: 185.2 ms per kick measured over 248 kicks in the pump, spin and trace captures, 185.1 ms emulated from the driver arithmetic; the full-step reading of MAX_ACCEL would give 110 ms, so the microstep reading Experiment 03 made is confirmed a second way. The balance loop uses `apply_acceleration` with a software clamp of 131071 microsteps/s^2 and never sees MAX_ACCEL; the golden trace's balance columns show the stock controller commanding 43 to 58 rad/s^2 over 50 ms windows in the first 300 ms, which is the rotor PID's start-up and a 20 degree rotor step reference the boot configuration enables, and 15 rad/s^2 at the 99th percentile in the hold. The kick law is the encoder's zero crossing firing a move against the bob's travel, the direction flipped at each detected peak, amplitudes 200, 200, 160 by the previous half-swing's peak against 600 and 1000 counts, handover within 1 degree of upright with no rate condition. Sixteen kicks in the golden trace at 0.004, 0.238, 0.645, 1.050, 1.495, 1.927, 2.385, 2.856, 3.340, 3.850, 4.373, 4.909, 5.484, 6.098, 6.777 and 7.573 s; half-swing peaks 57, 189, 246, 307, 356, 421, 471, 534, 582, 647, 697, 771, 835, 927, 1020 counts, then 1191 on the final approach. ADR-0004 carries the decision; the sweep in this experiment that fitted a clamp to that profile is annotated in the write-up and kept.

## The firmware's swing-up in simulation

**Kick law, LQR, rest start, 4 kHz, 256 identical episodes.** `--pump firmware --start-at-rest`. Kicks at 0.26, 0.65, 1.07, 1.50, 1.95, 2.40, 2.87 s on the golden trace's clock (board: 0.238, 0.645, 1.050, 1.495, 1.927, 2.385, 2.856), 20 kicks to the 1 degree handover at 11.57 s against the board's 16 and 8.02 s; amplitudes 150 then 200 through kick 19, 160 from kick 20. Handover: tilt 0.9 degrees, rate 1.19 rad/s, mode 1.07 rad/s, arm 0.29 rad at rest. LQR clamped at 11.78: held 0, terminated 256 on travel. The spread-start LQR run and the two policies at 11.78 were stopped after this result; the policies' commands cannot exceed the LQR's clamp. Files `kick_*_lqr_rest.csv`.

**Decision.** Retrain the momentum task at an action scale of 40 rad/s^2 as a labelled hypothesis (ADR-0004), reset mode range scaled to plus or minus 3.06 rad/s, three seeds, then the firmware-pump handover with `--policy-bound 40`. The board's mode `b` scales its command by the same constant, so the deployed bound and the trained bound stay one number.

**Momentum policy at 11.78 under the firmware pump, spread starts.** 256 handovers, held 115: every one with the unstable mode below 0.9 rad/s at handover, 10 of the 26 between 0.9 and 1.011, one of the 126 exceeding 1.011 rad/s. Median arrival mode 1.00 rad/s. The wall is the recoverable bound of the trained scale, not the policy. Files `kick_episodes_momentum.csv`, `kick_kicks_momentum.csv`.

**40 rad/s^2 hypothesis, momentum task, seeds 1 to 3, 300 iterations.** Reset mode range scaled to plus or minus 3.06 rad/s. Rewards at 299: 6003, 7456, 5662; episode lengths 3162, 3836, 2924 of 5000. Seed 1 evaluated with a 2 s settle from momentum starts: hold 0.707 at kicks 0 and 1.0 rad/s, recovery 0.371 at 2.0, none at 3.0; terminations on travel throughout. `recovery_a40.csv`.

**Seed 1 at 40 through the firmware pump, one rig from rest, recorded.** Handover at 11.58 s, held to the end of the 24 s clip, inside 3 degrees for the whole last 5 s, 0.30 degrees at the end, command peaking at the full 40 rad/s^2 in the catch and 8.5 rms after. `kick_trace_a40_rest.csv` (decimated five to one), also the second half of the conversion gate.

**Driver defect.** The 256-episode handover steps at 40 died in a second: the driver built its command in `$S` and looped over `$s`, and PowerShell treats the two as one variable, so the command became `3`. Renamed and rerun as `drive_a40b.ps1`.

**Deployment.** `board/policy_weights.h` re-exported from `checkpoints/momentum_a40_seed1_model_299.pt` (`--no-squash-actions`), `RL_ACCEL_BOUND_RAD_S2` set to 40 in the firmware header, image rebuilt, gate: 7 unit checks pass, trajectory replay 6e-6 rad/s^2 over 1242 steps.

**Seed 1 at 40 through the firmware pump, 256 episodes, rerun.** Spread starts: handover 256, held 256, terminated 0, median handover 11.50 s after 20 kicks, arrival mode rms 0.99 rad/s. Rest start: 256 of 256, handover 11.58 s, mode 1.07. Files `kick_episodes_a40.csv`, `kick_episodes_a40_rest.csv`, `kick_kicks_a40.csv`; the four firmware-pump rows in `handover_firmware.csv`.

## On the board, 2026-09-06

Mode b, the deployed 40 rad/s^2 checkpoint, at the desk with a hand on the supply.

**Defect 1, the estimator reset.** The glue called `observer_reset` at the handover, so the policy read zero pendulum rate for its first 16 samples, 32 ms of a 136 ms unstable time constant. The first attempt moved the arm slightly and dropped the pendulum. Running the estimator through the swing-up instead is wrong for a second reason: that loop polls every 3.25 ms against the window's fixed 2 ms, which scales rates by 1.6, and the attempt that did read 3.62 rad/s where the last swing-up samples give 2.2. The board now fits the arrival rate over the swing-up's last eight samples at their true timestamps and calls `observer_seed`.

**Defect 2, the control loop lag.** The stock firmware writes a 40 byte report every control cycle, 1.7 ms of blocking transmit in a 2 ms period at 230400 baud. The PID fits underneath it; the policy at the firmware's own optimisation level does not. The loop fell behind about 0.5 ms per cycle and the stock lag check broke out after 19 cycles, hard-stopping the motor 38 ms into the catch, which from outside looked like the policy doing nothing. The capture that diagnosed it carries the stock report's own 9-field lines showing the command pinned at the negative rail and the pendulum walking away. The report is suppressed in mode b; the hold logs to RAM at full rate and dumps afterwards.

**Defect 3, a simulation bound on a machine.** The glue stopped the run when the arm passed pi from the handover. The first real catch hit it at 1.5 s while holding the pendulum inside 3 degrees, with the arm decelerating at 1.3 rad/s^2 and roughly 20 degrees from turning back. Travel is not a failure here: the tilt sweep turns the arm through a full revolution and the cable does not bind. Removed, and the stock firmware's own 240 degree rotor limit is bypassed in this mode for the same reason. The fall stop went from 20 to 30 degrees on the same argument.

**A change tried and reverted.** With the last kick always the full 200 microsteps, the two-stage back-off never fires before the top, so the arrival is whatever that kick gives. Softening it for mode b (the upper band at 750 counts and 120 microsteps higher) stopped the pendulum reaching the top at all, and the swing-up is not the thing under test. Reverted; every mode runs the schedule that produced the golden trace.

**Results.** Mode b now retries after each attempt, so one capture holds a series. Of the five attempts in `hardware_rl_balance_series.tsv`, two held, 9.7 s and 15.7 s, and the best kept the pendulum inside 3 degrees for 97 percent of the hold at a tilt rms of 1.83 degrees. The swing-up matched the golden trace: 16 kicks over 8.03 s. Arrivals across the whole session ran 1.77 to 3.91 rad/s read off the bench, where the simulated swing-up arrives at 1.07 and the 40 rad/s^2 bound arrests 3.43. Only the retained captures are evidence: across all five committed .tsv files the twelve arrivals run 1.37 to 3.12 with a median of 2.33, so 3.91 is on record but not in a committed log. Five attempts do not separate a catch from a loss by arrival rate: the gentlest, 1.77, was lost and 2.11 held for 15.7 s.

**Three of three, and the chatter.** The a60c policy (60 rad/s^2, charged for the arm's position and its speed) held all three attempts for the full 30 s window. Tilt rms 1.47, 2.81 and 4.11 degrees, inside 3 degrees for 90, 78 and 65 percent of samples, arm spans 57, 105 and 172 degrees, arrivals 1.37, 2.96 and 2.83 rad/s. `hardware_rl_balance_a60c.tsv`.

The rod shakes throughout. Measured over the first two seconds of each hold at 500 Hz: the command changes sign 30, 28 and 22 times a second, rms 37.8, 38.7 and 36.8 rad/s^2, mean 0.3, 0.1 and 0.9. The same policy in simulation reverses 54 times a second at an rms of 9.3 with a tilt rms of 0.41 degrees, so the dithering is learned and the machine amplifies it about fourfold; the amplification is unexplained and backlash, compliance and step loss under reversal are the candidates.

The reward never priced it. `rew_scale_action_rate` is -0.01 on the squared normalised change, which at 1.6 rad/s^2 per step against a 60 bound charges 7.1e-6 per step against an alive term of 1.0; `rew_scale_action` charges 2.4e-4 at the observed amplitude. Both came from the cartpole template. Sweeping the action-rate weight at 0.5, 3 and 15, one seed each, traced through the firmware handover so the reversals can be counted.

**Evaluating and dropping a command filter.** A first-order low-pass on the policy's command at 40 Hz, in the glue, on the reasoning that the chatter is amplified fourfold by the machine and that a filter attacks the amplification where the model cannot. It made the hold worse on the bench, so it is gone from the firmware; the rebuilt image is byte-identical to the one that held three of three without it. The first attempt at it was also unreadable for a separate reason worth remembering: the board had been swinging up against an unpowered motor for ninety seconds, so its swing-up state had been tracking a pendulum that never moved, and connecting the supply mid-attempt produced a full turn and a drop that had nothing to do with the filter. A motor with no supply reports a rotor position of exactly zero on every sample, which is the tell.

**Action-rate sweep, three seeds.** One seed each at `--action-rate-weight` 0.5, 3 and 15, everything else the a60c configuration, then each through the firmware swing-up over 256 episodes with a trace. Catch rates 256, 29 and 0 of 256; the failures at 3 and 15 are the arm reaching the travel bound. Reversals per second over the first two seconds of environment 0's hold, against the deployed a60c's 54 at an rms of 9.27 rad/s^2: 32 at 2.83, 20 at 0.91, and at 15 the policy is falling rather than holding so its numbers do not describe chatter. Tilt rms 0.41, 0.46, 0.61 degrees. The per-step arithmetic in the write-up suggested a weight near 30; the ceiling is between 0.5 and 3, because the charge competes with the catch and not only with the alive term. `chatter_sweep.csv`.

**Deployment.** `board/policy_weights.h` re-exported from `checkpoints/momentum_a60d_seed1_model_299.pt` (`--no-squash-actions`, action range -1.108 to 1.721 against the a40 checkpoint's -5.690 to 7.670). Bound already 60 in the firmware header, so only the weights changed. Gate: 7 unit checks pass, trajectory replay 5e-6 rad/s^2 over 9316 rows with no row at the rail. Image `edukit-rl-balance-a60d.bin`, registered as `rl-balance-a60d` and copied over the default `rl-balance`; a60c is kept as `rl-balance-a60c` to reflash without a rebuild.

## On the board, 2026-09-07

Mode b, the a60d checkpoint (60 rad/s^2, action-rate weight 0.5), one 180 s capture holding two attempts. `hardware_rl_balance_a60d.tsv`.

**Results.** Attempt 1 arrived at -1.95 rad/s and held 10.9 s until the operator pushed the pendulum by hand; it arrested the arm within 30 degrees, came back inside 3.5 degrees, and went over on a second push. Attempt 2 arrived at -2.39 and held the full 30 s window. Both arrivals are negative where the previous session's three were positive, so the kick law hands over from either side and the policy catches both.

**The measurement window was wrong.** The chatter numbers reported the day before, 22 to 30 reversals a second at an rms of 37 rad/s^2, were taken over the first two seconds after the handover, which is the catch and not the hold. Split at 5 s, the a60c policy's settled hold is 12 to 13 reversals a second at an rms of 43.8, higher than the transient. The settled window is the one to quote.

**The fix, measured.** Settled command rms 43.80 rad/s^2 at weight 0.01 against 4.28 at 0.5, a factor of ten, where the simulation over the same window predicted six. The noisy policy sits on its 60 rad/s^2 rail for 32 percent of the settled hold; the simulated one peaks at 17.4 and never approaches it. Reversals per second on the machine 12.4 against 10.9, essentially unchanged, but that is saturation rather than steadiness: in simulation, where nothing rails, the same change takes reversals from 36.5 to 11.3. Amplitude was the measure that mattered and the count misled in both directions. The machine multiplies the noisy command by 3.9 and the quiet one by 2.3, so the amplification grows with the command and is not a constant gain, which is the first evidence about its shape. Cost: the quiet policy sits at a standing tilt offset near 1.6 degrees against the noisy one's 0.37 rms about zero, both inside 3 degrees for every settled sample; whether that is the reward or the baseplate's 0.9 degree tilt at this arm position is not separated. `plot_chatter.py` draws it.
