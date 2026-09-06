# Milestone 04: refit the simulation

Reproduce in simulation what [Milestone 03](M3-hardware-bringup.md) measured on the hardware.

## Goals

- [x] A harness drives the simulated model through the hardware's probes and compares the two with the same analysis code.
- [x] Each discrepancy [Milestone 03](M3-hardware-bringup.md) measures is either represented in the model or recorded as a known gap.
- [ ] The reconciled simulation reproduces a logged hardware trace.

Met by [Experiment 04](../experiments/04-model-reconciliation/writeup.md), except the third gate. The capture logs nothing through the 16 windows that hold the rotor's travel, so it can't separate a model error from a gap in the log. Settling the gate needs firmware that logs the rotor through the kick.
