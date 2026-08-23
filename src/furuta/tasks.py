"""Register the Edukit pendulum environment with Gymnasium on import."""

from __future__ import annotations

import gymnasium as gym

from furuta.env import FurutaEnv, FurutaEnvCfg

gym.register(
    id="Furuta-Balance-Direct-v0",
    entry_point="furuta.env:FurutaEnv",
    disable_env_checker=True,
    kwargs={"env_cfg_entry_point": FurutaEnvCfg},
)

__all__ = ["FurutaEnv", "FurutaEnvCfg"]
