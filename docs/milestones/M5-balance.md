# Milestone 05: balance

Train reinforcement learning balance policies and demonstrate sim-to-real transfer across three goals: near-vertical release, simulated swing-up handover, and physical hardware deployment.

## Goals

- [x] A trained policy balances the pendulum for 30 seconds from near-vertical release in simulation.
- [x] The policy catches simulated swing-up handovers and maintains upright balance.
- [x] Microcontroller firmware deployment catches physical swing-up handovers and balances hardware.

Met by [Experiment 05](../experiments/05-balance/writeup.md). The first balance policy holds 30 seconds from near-vertical release in three of five seeds, 256 of 256 episodes each. The momentum-start policy then catches 256 of 256 simulated handovers at $40\text{ rad/s}^2$. On hardware, the exported C policy charged for arm position and arm speed catches all three physical handovers at $60\text{ rad/s}^2$, each holding the full 30 seconds. Charging for the command's step change afterwards cuts the settled command tenfold and stops the rod shaking. Actuator torque limits remain an open modeling hypothesis pending the bench step-loss ladder in [ADR-0004](../adrs/0004-two-actuator-paths.md).
