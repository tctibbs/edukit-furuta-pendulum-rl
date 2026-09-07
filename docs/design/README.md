# Detailed design

A detailed design document specifies a contract the code has to keep. These are reference material, edited whenever the thing they describe changes.

The neighbouring directories hold the rest of the picture.

- [Design inputs](../design-inputs/README.md) are the values the design must honour rather than choose.
- [Decision records](../adrs/README.md) each hold one choice, fixed at the moment it was made and never revised.
- [Experiments](../experiments/README.md) record what happened on a given day.

Those three record how the design came to be. This directory records what it is now.

## Documents

- [Reinforcement learning environment](rl-environment.md), the contract a policy trains against: observations, action, termination, resets, and reward.
