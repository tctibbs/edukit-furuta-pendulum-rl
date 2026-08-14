# Actuation and sensing

What the controller can command, and what it can observe.

| Quantity | Value | Source |
|---|---|---|
| Motor | NEMA-17, 200 full steps/rev | Manual Sec. 3 |
| Microstepping | 1/16 | Manual Sec. 3 |
| Rotor angle control gain | 17.778 step commands per degree (9.817e-4 rad per step command, 0.0563 deg/step) | Manual Table 2 |
| Rotor angle measurement gain | 8.889 steps per degree (1.963e-3 rad per step, 0.1126 deg/step) | Manual Table 2 |
| Pendulum encoder resolution | 2400 counts/rev, 6.667 counts per degree | Manual Table 2 |
| Encoder | LPD3806-600BM-G5-24C, 600 PPR, quadrature, NPN open collector, 5 to 24 V | Manual Sec. 3, unit label |

Commanded rotor resolution is twice the measured rotor resolution.

## The actuator is not a torque source

The rotor is a stepper driven in an acceleration-command mode: the control loop sets an acceleration, the firmware integrates it into a PWM step-rate change (Manual App. E, `apply_acceleration()`). The plant seen by the controller is a double integrator from commanded acceleration to rotor angle, not a torque-in / angle-out second-order mechanical system.

Off-the-shelf pendulum environments assume a torque or force actuator. Anything driving this rotor commands angular acceleration instead, with the step-rate saturation and the 1/16-microstep quantization modeled. A controller designed against a torque actuator will not drive this one.
