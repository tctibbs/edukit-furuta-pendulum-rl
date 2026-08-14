# Geometry and mass

| Symbol | Quantity | Value | Source |
|---|---|---|---|
| l | Pendulum length, rotor arm to pendulum mass | 0.235 m | Manual Table 2 |
| L | Pendulum rod length used by the model | 0.258 m | Manual App. D, Pendulum Dynamics |
| r | Rotor arm length | 0.14 m | Manual Table 2, App. D, Pendulum Dynamics |
| m | Pendulum mass | Not given | Cancels in the linear model but not in the actuator torque budget, so it has to be weighed |
| g | Gravitational acceleration | 9.806 m/s^2 | Manual App. D, Pendulum Dynamics |

`l` and `L` are different quantities the manual states at two different values, see [dynamic-model.md](dynamic-model.md). The rotor arm's full length and its swept radius `r` are likewise two different spans of the same part.

Every value here is the manual's nominal for the kit as designed, not a measurement of this unit. The part masses are only reachable before assembly, so they have to be weighed then.
