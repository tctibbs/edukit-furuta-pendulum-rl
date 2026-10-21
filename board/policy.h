/* The balance actor, on the board.
 *
 * A 5-32-32-1 multilayer perceptron with ELU (alpha 1) after the first two layers: the
 * actor of the rsl_rl ActorCritic the policy was trained as, mean action only. The
 * weights come from the generated `policy_weights.h`, which `scripts/export_policy.py`
 * writes from a checkpoint. This file and `policy.c` are hand-written and do not change
 * when the policy is re-exported.
 *
 * The showcase build carries several policies at once, each exported under its own name
 * into `board/policies/`, and runs whichever the carousel selects through the `_with`
 * functions. Every one has the same shape, so a policy is only a set of weight pointers,
 * the bound it trained under and the way that bound was applied.
 *
 * C99, single-precision arithmetic only, no heap, no I/O. The weights are the only
 * globals, and they are const, so they live in flash.
 */
#ifndef POLICY_H
#define POLICY_H

/* Observations per step. This is the interface's number; the generated header carries
 * its own as POLICY_WEIGHTS_NUM_OBS, and `policy.c` fails the build with `#error` when
 * the two differ. A shared macro name was tried first and rejected: a differing
 * redefinition is only a warning on gcc and clang unless -Werror is passed, and the
 * firmware makefile does not pass it, so the mismatch compiled. Kept here so a caller
 * can size its buffer without pulling the weight arrays into its own translation
 * unit. */
#define POLICY_NUM_OBS 5

/* The width of both hidden layers, for every policy this project exports. */
#define POLICY_HIDDEN 32

/* One exported policy: its weights, row-major as W[out][in], the acceleration bound it
 * trained against in rad/s^2, and 1 when its task mapped the action through `tanh`
 * (`squash_actions`) or 0 when the actuator clamped it. */
typedef struct policy {
    const char *name;
    const float *w1, *b1, *w2, *b2, *w3, *b3;
    float a_max;
    int squash;
} policy_t;

/* The mean action for one observation vector, unbounded, as the network emits it.
 * `obs` is [cos(tilt), sin(tilt), pendulum_rate, rotor_angle, rotor_rate], the order
 * `observer_update` fills. */
float policy_forward(const float obs[POLICY_NUM_OBS]);

/* The rotor acceleration command in rad/s^2: the action bounded to [-1, 1] and scaled
 * by `a_max`, the acceleration bound the policy was trained against. How it is bounded
 * is fixed at export time by POLICY_SQUASH_ACTIONS in `policy_weights.h`, because the
 * simulation did it two ways and a policy is only valid under the one it trained with:
 * `tanh` when the task set `squash_actions` (`FurutaEnv._pre_physics_step` in
 * src/furuta/env.py), else the clamp in `AccelerationCommandActuator.step`
 * (src/furuta/actuator.py). The two differ by up to 24 percent of `a_max`, at a raw
 * action of magnitude 1. Converting rad/s^2 into the drive's own command unit is the
 * caller's job. */
float policy_command(const float obs[POLICY_NUM_OBS], float a_max);

/* 1 when `policy_command` maps the action through `tanh`, 0 when it clamps: the
 * POLICY_SQUASH_ACTIONS this object was compiled with, for a caller that wants to
 * report or check which policy it is carrying. */
int policy_squash_actions(void);

/* The same two functions for any exported policy, bounded and scaled by the policy's
 * own `squash` and `a_max`. The arithmetic is the same operations in the same order,
 * so the default policy gives the same bits either way. */
float policy_forward_with(const policy_t *p, const float obs[POLICY_NUM_OBS]);
float policy_command_with(const policy_t *p, const float obs[POLICY_NUM_OBS]);

#endif /* POLICY_H */
