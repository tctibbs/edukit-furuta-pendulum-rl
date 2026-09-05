# Milestone 01: Isaac Lab bring-up

Isaac Lab is this project's simulation environment. The Architecture Decision Record (ADR) behind that choice is [ADR-0001](../adrs/0001-simulation-environment.md). The goal here is to run Isaac Lab headless on the training host, driven from the workstation, and get results back. No hardware and no pendulum environment needed.

This milestone targets `Isaac-Cartpole-Direct-v0`, Isaac Lab's hello world simulation, which comes with working hyperparameters.

## Goals

- [x] Isaac Lab runs headless on the training host, usable over SSH.
- [x] The cartpole environment trains end to end.
- [x] A sweep measures throughput against parallel environment count.
- [x] The recorder captures a demo video.

Met by [Experiment 01](../experiments/01-cartpole-bringup/writeup.md).
