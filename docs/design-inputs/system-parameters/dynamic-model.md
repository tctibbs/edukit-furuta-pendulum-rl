# Validated dynamic model

The manual derives a linearized Furuta model and validates it against a measured frequency response. The linearization is about the upright, so gains designed from this model hold only near it. That's why the manual pairs them with a separate swing-up.

| Symbol | Quantity | Manual | Source |
|---|---|---|---|
| $f_{susp}$ | Suspended-mode natural frequency | 1.19 Hz | Manual App. D |
| $\omega_g^2$ | Gravitational term | 55.85 (rad/s)^2 with rotor inertia, 57.01 without | Manual App. D |
| $\omega_r^2$ | Rotor coupling term | 0.803 (rad/s)^2 | Manual App. D |
| $2 I_{rotor} / (m L^2)$ | Normalized rotor-shaft inertia | 0.0139 | Manual App. D |
| $Q$ | Quality factor of the suspended oscillation | 20 nominal | Manual App. D |
| $I_{pend}$ | Pendulum moment of inertia | $\tfrac{1}{3} m l^2$, uniform rod about its end | Manual App. D |
| $\gamma$ | Pendulum pivot damping coefficient | Not tracked, see below | Manual App. D |

Equation of motion, small angle, normalized. This is the manual's rearranged form on page 145, the one the published constants follow.

```math
\left(\frac{2}{3} + \frac{2 I_{rotor}}{m L^{2}}\right)\ddot{\theta}
= \frac{g}{L}\theta + \frac{r}{L}\ddot{\phi} - \frac{\gamma}{m L}\dot{\theta}
```

giving

```math
\omega_g^{2} = \frac{g}{L\left(\frac{2}{3} + \frac{2 I_{rotor}}{m L^{2}}\right)}
\qquad
\omega_r^{2} = \frac{r}{L\left(\frac{2}{3} + \frac{2 I_{rotor}}{m L^{2}}\right)}
```

where $\theta$ is pendulum angle from the gravity vector and $\phi$ is rotor angle. Substituting $L$, $r$ and the normalized shaft inertia reproduces 55.85 and 0.803 (rad/s)^2.

The line preceding the rearrangement carries an extra $-m \frac{l^{2}}{4} \ddot{\theta}$. The manual drops it in the next step and no published constant reflects it. Carried through it would put $\omega_g^2$ near 32 instead of 55.85, so use the rearranged form.

The damping coefficient $\gamma$ isn't tracked. The manual's own $Q = \omega_g \frac{m l}{\gamma}$ disagrees with the preceding equation of motion by a factor of $1 / \left(\frac{2}{3} + \frac{2 I_{rotor}}{m L^{2}}\right)$, about 1.47, so it isn't a reliable route to $Q$. Derive damping from $Q$ directly, $c = I \omega / Q$, which never needs $\gamma$.

The appendix writes $l$ for the length this table calls $L$, 0.258 m, not the 0.235 m that Table 2 calls $l$. The same letter means different quantities in the two places. Using the rod length throughout reproduces both constants.
