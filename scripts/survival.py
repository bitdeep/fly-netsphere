"""Explicit game-scale reserves; not a metabolic or neural hunger model."""
import math

INITIAL_RESERVE = .70
DRAIN = {"energy": .002, "water": .003}  # Fractions of capacity / physical second.
PORTION = .20
INTAKE_PER_SECOND = 5.


class Survival:
    def __init__(self):
        self.generation = 0
        self.revision = 0
        self._key = None
        self.restart()

    def restart(self):
        self.generation += 1
        self.energy = self.water = INITIAL_RESERVE
        self.age = 0.
        self.alive = True
        self.cause = None
        self.consumed = {"energy": 0., "water": 0.}

    def advance(self, seconds):
        if not math.isfinite(seconds) or seconds < 0:
            raise ValueError("Survival requires nonnegative physical time")
        if not self.alive:
            return False
        energy_time, water_time = self.energy/DRAIN["energy"], self.water/DRAIN["water"]
        elapsed = min(seconds, energy_time, water_time)
        self.age += elapsed
        self.energy = max(0., self.energy-DRAIN["energy"]*elapsed)
        self.water = max(0., self.water-DRAIN["water"]*elapsed)
        if seconds >= min(energy_time, water_time):
            self.alive = False
            self.cause = "energy" if energy_time <= water_time else "water"
            setattr(self, self.cause, 0.)
            return True
        return False

    def receive(self, resource, available, seconds):
        if resource not in DRAIN or not all(math.isfinite(x) and x >= 0
                                           for x in (available, seconds)):
            raise ValueError("Invalid resource transfer")
        if not self.alive:
            return 0.
        amount = min(available, 1.-getattr(self, resource), INTAKE_PER_SECOND*seconds)
        setattr(self, resource, getattr(self, resource)+amount)
        self.consumed[resource] += amount
        return amount

    def snapshot(self):
        # Quantize only transport. The authoritative reserves retain precision.
        key = (self.generation, self.alive, self.cause, round(self.age, 1),
               round(self.energy, 4), round(self.water, 4),
               round(self.consumed["energy"], 4), round(self.consumed["water"], 4))
        if key != self._key:
            self._key = key
            self.revision += 1
        return {"revision": self.revision, "generation": key[0], "alive": key[1],
                "cause": key[2], "age_seconds": key[3], "energy": key[4], "water": key[5],
                "consumed": {"energy": key[6], "water": key[7]}}


DESCRIPTOR = {
    "model": "Simplified survival reserves; not biological metabolism",
    "initial": INITIAL_RESERVE, "drain_per_second": DRAIN,
    "portion_capacity": PORTION, "intake_per_second": INTAKE_PER_SECOND,
    "clock": "Executed physical time; Pause freezes reserves",
}
