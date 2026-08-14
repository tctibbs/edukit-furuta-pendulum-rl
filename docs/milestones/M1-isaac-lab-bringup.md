# Milestone 01: Isaac Lab bring-up

[ADR-0001](../adrs/0001-simulation-environment.md) chose Isaac Lab as this project's simulation environment. The goal here is to run it headless on the training host, driven from the workstation, and get results back. No hardware and no pendulum environment needed.

This milestone targets `Isaac-Cartpole-Direct-v0`, Isaac Lab's hello world simulation, which comes with working hyperparameters.

## Goals

- [ ] Isaac Lab runs headless on the training host, usable over SSH.
- [ ] The cartpole environment trains end to end.
- [ ] Throughput is measured against parallel environment count.
- [ ] A demo video is recorded.
