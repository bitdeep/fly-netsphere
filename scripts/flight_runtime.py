"""Continuous, force-driven flybody flight. Lengths are centimetres.

The reference is a command to the pretrained controller, never a write to the
animal's pose. Only initialize_episode sets the physical initial state.
"""
from __future__ import annotations

import os
from pathlib import Path

os.environ.setdefault("MUJOCO_GL", "egl")
os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "2")

import numpy as np
from dm_control import composer
from dm_control.composer.observation import observable
from dm_control.locomotion.arenas import floors

from flybody.fruitfly.fruitfly import FruitFly
from flybody.quaternions import get_dquat_local, mult_quat
from flybody.tasks.base import Flying
from flybody.tasks.pattern_generators import WingBeatPatternGenerator
from flybody.tasks.task_utils import canonical2real, com2root

ROOT = Path(__file__).resolve().parents[1]
CONTROL_DT = 0.0002
PHYSICS_DT = 0.00005


def attitude(heading, pitch=-47.5, bank=0.0):
    """MuJoCo wxyz body attitude, yaw followed by pitch and roll."""
    heading = np.asarray(heading)
    q = np.zeros(heading.shape + (4,))
    q[..., 0] = np.cos(heading / 2)
    q[..., 3] = np.sin(heading / 2)
    pitch = np.deg2rad(pitch)
    q = mult_quat(q, np.array([np.cos(pitch / 2), 0, np.sin(pitch / 2), 0]))
    bank = np.asarray(bank)
    qb = np.zeros(bank.shape + (4,))
    qb[..., 0] = np.cos(bank / 2)
    qb[..., 1] = np.sin(bank / 2)
    return mult_quat(q, qb)


class CircleReference:
    """Diagnostic command; not used as obstacle avoidance."""

    def __init__(self, speed=20.0, yaw_rate=0.0, height=3.0, pitch=-47.5):
        self.speed, self.yaw_rate, self.height = speed, yaw_rate, height
        self.pitch = pitch

    def sample(self, times):
        times = np.asarray(times)
        yaw = times * self.yaw_rate
        pos = np.zeros(times.shape + (3,))
        if abs(self.yaw_rate) > 1e-8:
            pos[..., 0] = self.speed / self.yaw_rate * np.sin(yaw)
            pos[..., 1] = self.speed / self.yaw_rate * (1 - np.cos(yaw))
        else:
            pos[..., 0] = self.speed * times
        pos[..., 2] = self.height
        quat = attitude(yaw, pitch=self.pitch)
        return com2root(pos, quat), quat

    def velocity(self, time):
        yaw = time * self.yaw_rate
        return np.array([self.speed * np.cos(yaw), self.speed * np.sin(yaw), 0])


class ContinuousFlight(Flying):
    def __init__(self, reference, arena, duration, seed=0):
        super().__init__(
            walker=FruitFly, arena=arena, time_limit=duration,
            add_ghost=False, num_user_actions=1, future_steps=5,
            initialize_qvel=True, disable_legs=True, joint_filter=0.0,
            floor_contacts=True,
        )
        self.reference = reference
        self.seed = seed
        self.wpg = WingBeatPatternGenerator(
            base_pattern_path=str(ROOT / "data/flight/wing_pattern_fmech.npy"))
        self.wing_actions = self.walker._action_indices["wings"]
        self.user_action = self.walker._action_indices["user"][0]
        self.walker.observables.add_observable("ref_displacement", self.ref_displacement)
        self.walker.observables.add_observable("ref_root_quat", self.ref_root_quat)
        self.preview = np.arange(6) * CONTROL_DT
        # Warp does not implement MuJoCo's optional no-slip postprocessor.
        # Both backends use identical settings; regular contact/friction remains.
        self.root_entity.mjcf_model.option.noslip_iterations = 0

    def initialize_episode_mjcf(self, random_state):
        super().initialize_episode_mjcf(random_state)
        if hasattr(self._arena, "configure_visual"):
            self._arena.configure_visual()

    def initialize_episode(self, physics, random_state):
        super().initialize_episode(physics, random_state)
        pos, quat = self.reference.sample(np.array([0.0]))
        self.walker.set_pose(physics, pos[0], quat[0])
        self.walker.set_velocity(physics, self.reference.velocity(0.0))
        wing_pos, wing_vel = self.wpg.reset(
            initial_phase=np.random.RandomState(self.seed).uniform(), return_qvel=True)
        physics.bind(self._wing_joints).qpos = wing_pos
        physics.bind(self._wing_joints).qvel = wing_vel

    @composer.observable
    def ref_displacement(self):
        def read(physics):
            pos, _ = self.reference.sample(physics.time() + self.preview)
            fly_pos, _ = self.walker.get_pose(physics)
            return self.walker.transform_vec_to_egocentric_frame(physics, pos - fly_pos)
        return observable.Generic(read)

    @composer.observable
    def ref_root_quat(self):
        def read(physics):
            _, quat = self.reference.sample(physics.time() + self.preview)
            _, fly_quat = self.walker.get_pose(physics)
            # Quaternion signs are physically equivalent, but the MLP expects
            # the short-arc representative close to [1, 0, 0, 0].
            delta = get_dquat_local(fly_quat, quat)
            return np.where(delta[:, :1] < 0, -delta, delta)
        return observable.Generic(read)

    def before_step(self, physics, action, random_state):
        action = np.array(action, copy=True)
        freq = self.wpg.base_beat_freq * (1 + self.wpg.rel_freq_range * action[self.user_action])
        base = self.wpg.step(freq)
        action[self.wing_actions] += base - physics.bind(self._wing_joints).qpos
        super().before_step(physics, action, random_state)

    def get_reward_factors(self, physics):
        return (1.0,)

    def check_termination(self, physics):
        return (not np.isfinite(physics.data.qpos).all()
                or physics.named.data.xpos["walker/thorax"][2] < 0.2
                or super().check_termination(physics))


def make_environment(reference, duration, arena=None, seed=0):
    task = ContinuousFlight(reference, arena or floors.Floor(), duration, seed)
    return composer.Environment(
        task=task, time_limit=duration, random_state=np.random.RandomState(seed),
        strip_singleton_obs_buffer_dim=True)


def step_cpu(env, policy, observation):
    return env.step(canonical2real(policy(observation), env.action_spec()))
