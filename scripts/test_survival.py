"""Conservation, clock partitioning and terminal-state checks without neural data."""
import unittest

from survival import Survival, DRAIN, PORTION


class SurvivalTests(unittest.TestCase):
    def test_clock_partitioning_and_zero_elapsed(self):
        whole, chunks = Survival(), Survival()
        whole.advance(37.)
        for _ in range(3700):
            chunks.advance(.01)
        self.assertAlmostEqual(whole.energy, chunks.energy, places=11)
        self.assertAlmostEqual(whole.water, chunks.water, places=11)
        frozen = chunks.snapshot()
        chunks.advance(0)
        self.assertEqual(chunks.snapshot(), frozen)

    def test_resource_conservation_capacity_and_independence(self):
        life = Survival()
        original_water = life.water
        remaining = PORTION
        for _ in range(5000):
            received = life.receive("energy", remaining, .0001)
            remaining -= received
        self.assertAlmostEqual(life.energy, .9)
        self.assertAlmostEqual(life.consumed["energy"]+remaining, PORTION)
        self.assertEqual(life.water, original_water)
        self.assertAlmostEqual(life.receive("energy", PORTION, 1), .1, places=11)
        self.assertEqual(life.receive("energy", PORTION, 1), 0)
        self.assertEqual(life.energy, 1.)

    def test_both_terminal_causes_cannot_be_fed_back_to_life(self):
        for cause in DRAIN:
            with self.subTest(cause=cause):
                life = Survival()
                setattr(life, cause, DRAIN[cause]*.1)
                self.assertTrue(life.advance(1))
                self.assertEqual(life.cause, cause)
                self.assertAlmostEqual(life.age, .1)
                frozen = life.snapshot()
                self.assertEqual(life.receive(cause, PORTION, 1), 0)
                self.assertFalse(life.advance(100))
                self.assertEqual(life.snapshot(), frozen)
                life.restart()
                self.assertTrue(life.alive)
                self.assertEqual((life.energy, life.water, life.age), (.7, .7, 0))
                self.assertEqual(life.generation, 2)

    def test_invalid_time_and_transfer_fail_closed(self):
        life = Survival()
        for value in (-1, float("nan"), float("inf")):
            with self.assertRaises(ValueError):
                life.advance(value)
            with self.assertRaises(ValueError):
                life.receive("energy", value, 1)
        with self.assertRaises(ValueError):
            life.receive("unbounded", 1, 1)


if __name__ == "__main__":
    unittest.main()
