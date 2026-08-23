# Geometry and mass

| Symbol | Quantity | Value | Source |
|---|---|---|---|
| l | Pendulum length, rotor arm to pendulum mass | 0.235 m | Manual Table 2, page 11 |
| L | Pendulum rod length used by the model | 0.258 m | Manual App. D, Pendulum Dynamics, page 148 |
| r | Rotor arm length | 0.14 m | Manual Table 2, page 11 |
| m | Pendulum mass | Not given | Cancels in the linear model but not in the actuator torque budget, so it has to be weighed |
| g | Gravitational acceleration | 9.806 m/s^2 | Manual App. D, Pendulum Dynamics, page 148 |

`l` and `L` are different quantities the manual states at two different values, see [dynamic-model.md](dynamic-model.md). The rotor arm's full length and its swept radius `r` are likewise two different spans of the same part. Table 2 gives 0.14 m and App. D page 148 uses 0.141 m. The model takes Table 2's.

Every value here is the manual's nominal for the kit as designed, not a measurement of this unit. The part masses are only reachable before assembly, so they have to be weighed then.
