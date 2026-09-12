"""Physical and transport checks for one disconnected flybody animal."""
import copy
import unittest
import xml.etree.ElementTree as ET

import mujoco
import numpy as np

from serve_environment import Environment, PROBE_RADIUS, PROBE_START
from passive_fly import initialize_fly
from prepare_browser_fly import CACHE, SOURCE


class EnvironmentPhysicsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.env = Environment()

    def setUp(self):
        mujoco.mj_resetData(self.env.model, self.env.data)
        initialize_fly(self.env.model, self.env.data)
        self.env.fly_contacts_seen = False
        self.env.command({"action": "drop"})

    def advance(self, seconds):
        for _ in range(round(seconds/self.env.model.opt.timestep/10)):
            mujoco.mj_step(self.env.model, self.env.data, nstep=10)
            self.env._sample_contacts()

    def test_free_fall_matches_centimetre_gravity(self):
        # Compare with the analytic trajectory, allowing one integration step's error.
        model, data = self.env.model, self.env.data
        start_time = data.time
        # Isolate gravity analytically. Runtime retains the source air density/
        # viscosity; the other contact/settling checks use those air parameters.
        density, viscosity = model.opt.density, model.opt.viscosity
        try:
            model.opt.density = model.opt.viscosity = 0.
            mujoco.mj_step(model, data, nstep=round(.1/model.opt.timestep))
        finally:
            model.opt.density, model.opt.viscosity = density, viscosity
        dt = data.time-start_time
        expected = PROBE_START[2] - .5 * 981 * dt**2
        self.assertAlmostEqual(data.qpos[self.env.probe_qpos+2], expected, delta=981*model.opt.timestep*dt*.55)
        self.assertAlmostEqual(data.qvel[self.env.probe_dof+2], -981*dt, places=7)
        self.assertFalse(np.any(data.contact.geom[:data.ncon] == self.env.probe_geom))

    def test_probe_lands_on_existing_bridge(self):
        model, data = self.env.model, self.env.data
        touched = set()
        for _ in range(round(.8/model.opt.timestep/10)):
            mujoco.mj_step(model, data, nstep=10)
            for contact in data.contact[:data.ncon]:
                if self.env.probe_geom in contact.geom:
                    touched.update(model.geom(int(g)).name for g in contact.geom)
        self.assertIn("bridge_0", touched)
        self.assertAlmostEqual(data.qpos[self.env.probe_qpos+2], -8 + .45 + PROBE_RADIUS, delta=.025)
        self.assertLess(np.linalg.norm(data.qvel[self.env.probe_dof:self.env.probe_dof+3]), .01)
        self.assertGreaterEqual(data.tree_asleep[model.body_treeid[self.env.probe_id]], 0)
        # A second release must wake a sleeping particle naturally.
        self.env.command({"action": "drop"})
        mujoco.mj_step(model, data, nstep=100)
        self.assertLess(data.qpos[self.env.probe_qpos+2], PROBE_START[2]-.04)

    def test_drop_preserves_global_clock(self):
        self.advance(.15)
        self.env.data.time = 123.456
        q, v = self.env.probe_qpos, self.env.probe_dof
        fly_qpos = self.env.data.qpos[:q].copy()
        fly_qvel = self.env.data.qvel[:v].copy()
        self.env.command({"action": "drop"})
        self.assertEqual(self.env.data.time, 123.456)
        np.testing.assert_allclose(self.env.data.qpos[q:q+3], PROBE_START)
        np.testing.assert_array_equal(self.env.data.qpos[:q], fly_qpos)
        np.testing.assert_array_equal(self.env.data.qvel[:v], fly_qvel)

    def test_commands_reject_unbounded_or_ambiguous_values(self):
        for command in [[], {"action": "speed", "value": True},
                        {"action": "speed", "value": 100},
                        {"action": "pause", "paused": "false"},
                        {"action": "drop", "position": [0, 0, 0]}]:
            with self.subTest(command=command), self.assertRaises(ValueError):
                self.env.command(command)

    def test_passive_anatomy_and_collision_contract(self):
        world = self.env.world
        self.assertIsNone(world["neural_controller"])
        self.assertEqual(world["fly_body"]["neural_controller"], "disconnected")
        self.assertEqual(len(world["fly_body"]["bodies"]), 67)
        self.assertEqual(len(world["geoms"]), 383)
        self.assertTrue(all(geom["collision"] for geom in world["geoms"]))
        for view in world["views"]:
            self.assertGreater(float(self.env.city.clearance(np.array([view["position"]]))[0]), .3)
        # Cache reduction must leave joint, actuator, contact and passive contracts intact.
        original, cached = ET.parse(SOURCE), ET.parse(CACHE/"physics.xml")
        for tag in ["joint", "tendon", "actuator", "contact", "sensor"]:
            # XML indentation is presentation, so compare trees without whitespace.
            def canonical(tree):
                node = copy.deepcopy(tree)
                for child in node.iter():
                    child.text = child.tail = None
                return ET.tostring(node)
            self.assertEqual([canonical(x) for x in original.iter(tag)],
                             [canonical(x) for x in cached.iter(tag)], tag)
        original_geoms = {g.get("name"): g.attrib for g in original.iter("geom") if g.get("name") and not g.get("mesh")}
        cached_geoms = {g.get("name"): g.attrib for g in cached.iter("geom") if g.get("name")}
        self.assertEqual(original_geoms, cached_geoms)
        self.advance(.8)
        self.assertTrue(self.env.fly_contacts_seen)
        self.assertTrue(np.isfinite(self.env.data.qpos).all())
        self.assertFalse(self.env.data.warning.number.any())
        self.assertFalse(self.env.data.actuator_force.any())
        self.assertGreater(self.env.data.xpos[self.env.fly_root_id, 2], -7.55)
        self.assertLess(self.env.data.xpos[self.env.fly_root_id, 2], -7.4)
        self.assertLess(self.env.fly_sleep_radius, .5)
        self.assertGreater(self.env.fly_sleep_radius, .1)

    def test_native_sleep_bounds_drift_and_external_force_wakes_body(self):
        model, data = self.env.model, self.env.data
        for _ in range(60):
            self.advance(.1)
            if data.tree_asleep[self.env.fly_tree] >= 0:
                break
        self.assertGreaterEqual(data.tree_asleep[self.env.fly_tree], 0)
        mujoco.mj_kinematics(model, data)
        resting = data.xpos[self.env.fly_body_ids].copy()
        position = data.qpos.copy()
        # Compare against uninterrupted awake dynamics for 200 ms after settling.
        flags = model.opt.enableflags
        try:
            model.opt.enableflags &= ~int(mujoco.mjtEnableBit.mjENBL_SLEEP)
            reference = mujoco.MjData(model)
            reference.qpos[:] = position
            mujoco.mj_forward(model, reference)
            mujoco.mj_step(model, reference, nstep=2000)
            mujoco.mj_kinematics(model, reference)
            drift = np.linalg.norm(reference.xpos[self.env.fly_body_ids]-resting, axis=1).max()
            print(f"\nSleep: {data.time:.3f} simulated s; awake reference drift: {drift*10000:.3f} µm",
                  flush=True)
            # This passive viewer accepts native sleep error below the measured
            # visual reduction displacement, not sub-micrometre biomechanics.
            self.assertLess(drift*10000, self.env.fly_description["max_visual_displacement_um"])
        finally:
            model.opt.enableflags = flags
        mujoco.mj_step(model, data, nstep=2000)
        np.testing.assert_array_equal(data.qpos, position)
        data.xfrc_applied[self.env.fly_root_id, 0] = .1
        mujoco.mj_step(model, data, nstep=100)
        self.assertLess(data.tree_asleep[self.env.fly_tree], 0)
        self.assertGreater(np.linalg.norm(data.qvel[:self.env.probe_dof]), 0)
        self.assertFalse(data.warning.number.any())

    def test_unchanged_poses_and_trail_are_not_retransmitted(self):
        self.env._cache_fly_pose()
        first = self.env.snapshot()
        revision = first["fly"]["pose_revision"]
        trail_version = (first["probe"]["generation"], first["probe"]["trail_count"])
        self.env._cache_fly_pose()
        self.assertEqual(revision, self.env.fly_pose_revision)
        delta = self.env.snapshot(revision, trail_version)
        self.assertNotIn("poses_b64", delta["fly"])
        self.assertNotIn("trail", delta["probe"])
        self.assertIn("poses_b64", self.env.snapshot()["fly"])


if __name__ == "__main__":
    unittest.main()
