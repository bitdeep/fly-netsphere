"""Receding-horizon geometric navigation; this is not a vision-trained brain."""
import numpy as np
from flight_runtime import attitude
from flybody.tasks.task_utils import com2root


class Navigator:
    def __init__(self, city, seed=0, avoid=True, pitch=-30.0):
        self.city, self.avoid, self.seed = city, avoid, seed
        self.pitch = pitch
        self.position = np.array([-38., -28., 4.])
        self.yaw, self.rate, self.climb, self.speed = 0., 0., 0., 20.
        self.time = 0.
        self.goals = np.array([
            [44, -28, 4], [44, 28, 6], [-44, 28, 5], [-44, -28, 4],
        ], dtype=float)
        self.goal_index = 0
        self.avoidance_updates = 0
        self.history = []

    def velocity(self, time):
        return np.array([self.speed*np.cos(self.yaw), self.speed*np.sin(self.yaw), self.climb])

    def sample(self, times):
        dt = np.asarray(times) - self.time
        yaw = self.yaw + self.rate*dt
        pos = np.broadcast_to(self.position, dt.shape+(3,)).copy()
        if abs(self.rate) > 1e-8:
            pos[..., 0] += self.speed / self.rate * (np.sin(yaw)-np.sin(self.yaw))
            pos[..., 1] += self.speed / self.rate * (np.cos(self.yaw)-np.cos(yaw))
        else:
            pos[..., :2] += dt[..., None]*self.velocity(0)[:2]
        pos[..., 2] += self.climb*dt
        quat = attitude(yaw, pitch=self.pitch)
        return com2root(pos, quat), quat

    def update(self, time, actual_root):
        dt = time-self.time
        if dt > 0:
            if abs(self.rate) > 1e-8:
                self.position[0] += self.speed/self.rate * (np.sin(self.yaw+self.rate*dt)-np.sin(self.yaw))
                self.position[1] += self.speed/self.rate * (np.cos(self.yaw)-np.cos(self.yaw+self.rate*dt))
            else:
                self.position[:2] += self.velocity(0)[:2]*dt
            self.position[2] += self.climb*dt
            self.yaw += self.rate*dt
        self.time = time
        goal = self.goals[self.goal_index % len(self.goals)].copy()
        if np.linalg.norm(np.asarray(actual_root)[:2]-goal[:2]) < 7:
            self.goal_index += 1
            goal = self.goals[self.goal_index % len(self.goals)].copy()
        # Small, smooth changes in preferred altitude rather than positional noise.
        goal[2] += .6*np.sin(time*.47+self.seed)
        desired = np.arctan2(goal[1]-actual_root[1], goal[0]-actual_root[0])
        angle = np.arctan2(np.sin(desired-self.yaw), np.cos(desired-self.yaw))
        nominal = np.clip(angle*3, -4.5, 4.5)
        desired_climb = np.clip((goal[2]-actual_root[2])*2, -4, 4)
        turn, climb = nominal, desired_climb
        if self.avoid:
            rates = np.unique(np.r_[np.linspace(-4.5, 4.5, 19), nominal, self.rate])
            climbs = np.unique(np.r_[-4., 0., 4., desired_climb, self.climb])
            rr, cc = np.meshgrid(rates, climbs)
            rr, cc = rr.ravel(), cc.ravel()
            # Start predictions at measured body position; commands only steer forces.
            pos = np.broadcast_to(np.asarray(actual_root), (len(rr), 3)).copy()
            heading = np.full(len(rr), self.yaw)
            omega = np.full(len(rr), self.rate)
            vertical = np.full(len(rr), self.climb)
            samples = []
            for k in range(25):
                omega += np.clip(rr-omega, -.8, .8)
                vertical += np.clip(cc-vertical, -1.2, 1.2)
                heading += omega*.04
                pos += np.stack([self.speed*np.cos(heading), self.speed*np.sin(heading), vertical], -1)*.04
                samples.append(pos.copy())
            points = np.stack(samples, 1)
            clearance = self.city.clearance(points).min(axis=1)
            progress = np.linalg.norm(points[:, -1, :2]-goal[None, :2], axis=-1)
            score = (progress + .4*np.abs(points[:, -1, 2]-goal[2])
                     + .22*(rr-self.rate)**2 + .08*(cc-self.climb)**2
                     + 1.8/np.maximum(clearance, .1)
                     + 10000*np.maximum(1.15-clearance, 0))
            chosen = int(np.argmin(score))
            turn, climb = rr[chosen], cc[chosen]
            if abs(turn-nominal) > .25 or abs(climb-desired_climb) > .5:
                self.avoidance_updates += 1
        self.rate += np.clip(turn-self.rate, -.20, .20)
        self.climb += np.clip(climb-self.climb, -.30, .30)
        self.history.append([time, *np.asarray(actual_root), self.rate, self.climb, self.goal_index])
