#include "policy.h"

#include <math.h>

#include "policy_weights.h"

/* The generated header has to be from an exporter that records the observation count
 * and the action bound, and its count has to be the interface's. These are `#error`
 * rather than a macro redefinition on purpose: a redefinition is a warning unless the
 * build passes -Werror, and the firmware makefile does not, so a mismatched export
 * compiled to a `policy_forward` that read past the caller's five-float array. */
#ifndef POLICY_WEIGHTS_NUM_OBS
#error "policy_weights.h predates the observation-count check; re-export it with scripts/export_policy.py"
#endif
#ifndef POLICY_SQUASH_ACTIONS
#error "policy_weights.h does not say how the action is bounded; re-export it with scripts/export_policy.py"
#endif
#if POLICY_WEIGHTS_NUM_OBS != POLICY_NUM_OBS
#error "policy_weights.h was exported for a different observation count than policy.h declares"
#endif
#if POLICY_SQUASH_ACTIONS != 0 && POLICY_SQUASH_ACTIONS != 1
#error "POLICY_SQUASH_ACTIONS must be 0 or 1"
#endif

/* The array sizes the exporter wrote must be the layer shapes this file assumes.
 * C99 has no static_assert; a negative array size fails the build in its place. */
#define POLICY_ASSERT(cond, name) typedef char policy_assert_##name[(cond) ? 1 : -1]
POLICY_ASSERT(sizeof(POLICY_W1) == sizeof(float) * POLICY_HIDDEN_1 * POLICY_NUM_OBS, w1);
POLICY_ASSERT(sizeof(POLICY_B1) == sizeof(float) * POLICY_HIDDEN_1, b1);
POLICY_ASSERT(sizeof(POLICY_W2) == sizeof(float) * POLICY_HIDDEN_2 * POLICY_HIDDEN_1, w2);
POLICY_ASSERT(sizeof(POLICY_B2) == sizeof(float) * POLICY_HIDDEN_2, b2);
POLICY_ASSERT(sizeof(POLICY_W3) == sizeof(float) * POLICY_HIDDEN_2, w3);
POLICY_ASSERT(sizeof(POLICY_B3) == sizeof(float), b3);

/* One dense layer, y = W x + b, with W row-major as W[out][in]. The products are summed
 * first and the bias added last, the op order of `x @ W.T + b` in the exporter's
 * reference forward, so the two round the same way as far as a scalar loop can. */
static void dense(const float *w, const float *b, int rows, int cols, const float *x,
                  float *y)
{
    for (int r = 0; r < rows; ++r) {
        const float *row = w + r * cols;
        float acc = 0.0f;
        for (int c = 0; c < cols; ++c) {
            acc += row[c] * x[c];
        }
        y[r] = acc + b[r];
    }
}

/* ELU with alpha 1: identity above zero, exp(x) - 1 at and below it. `expm1f` rather
 * than `expf(x) - 1.0f`, because the subtraction cancels for small negative x, which
 * is where most pre-activations of a trained layer land. */
static void elu_in_place(float *x, int n)
{
    for (int i = 0; i < n; ++i) {
        if (x[i] <= 0.0f) {
            x[i] = expm1f(x[i]);
        }
    }
}

float policy_forward(const float obs[POLICY_NUM_OBS])
{
    float hidden_1[POLICY_HIDDEN_1];
    float hidden_2[POLICY_HIDDEN_2];
    float out[1];

    dense(POLICY_W1, POLICY_B1, POLICY_HIDDEN_1, POLICY_NUM_OBS, obs, hidden_1);
    elu_in_place(hidden_1, POLICY_HIDDEN_1);
    dense(POLICY_W2, POLICY_B2, POLICY_HIDDEN_2, POLICY_HIDDEN_1, hidden_1, hidden_2);
    elu_in_place(hidden_2, POLICY_HIDDEN_2);
    dense(POLICY_W3, POLICY_B3, 1, POLICY_HIDDEN_2, hidden_2, out);
    return out[0];
}

int policy_squash_actions(void)
{
    return POLICY_SQUASH_ACTIONS;
}

float policy_command(const float obs[POLICY_NUM_OBS], float a_max)
{
    float action = policy_forward(obs);
#if POLICY_SQUASH_ACTIONS
    /* The bound the swing-up task trained under: `torch.tanh(action)` before the
     * actuator, whose clamp then never engages. */
    action = tanhf(action);
#else
    /* The bound the balance tasks trained under: the actuator's clamp. */
    if (action > 1.0f) {
        action = 1.0f;
    } else if (action < -1.0f) {
        action = -1.0f;
    }
#endif
    return action * a_max;
}
