"""Procedural, collidable megastructure. All lengths are centimetres."""
import io
import numpy as np
from PIL import Image, ImageDraw, ImageFont
from dm_control import composer, mjcf


def concrete_texture():
    """Deterministic procedural surface detail, not a photographic backdrop."""
    rng = np.random.RandomState(81)
    size = 768
    field = np.zeros((size, size), dtype=float)
    for resolution, amplitude in [(6, .085), (24, .045), (96, .025), (768, .018)]:
        noise = rng.normal(127, 25, (resolution, resolution)).clip(0, 255).astype(np.uint8)
        field += (np.asarray(Image.fromarray(noise).resize(
            (size, size), Image.Resampling.BICUBIC), float)-127)/25*amplitude
    field += .70
    # Formwork seams and subtle mineral streaks repeat in physical texture space.
    field[:, :3] -= .13
    field[:3, :] -= .13
    for _ in range(180):
        x, y = rng.randint(0, size, 2)
        length, width = rng.randint(20, 270), rng.randint(1, 5)
        field[y:min(y+length, size), x:min(x+width, size)] -= rng.uniform(.03, .16)
    # Large pour joints and thin branching cracks, with no repeated sci-fi labels.
    for x in (size//3, 2*size//3):
        field[:, x:x+2] -= .12
    for y in (size//4, 3*size//4):
        field[y:y+2, :] -= .08
    for _ in range(12):
        x, y = rng.randint(12, size-12, 2)
        for k in range(int(rng.randint(15, 100))):
            x = int(np.clip(x+rng.choice([-1, 0, 1]), 1, size-2))
            if y+k >= size:
                break
            field[y+k, x:x+1] -= .22
    rgb = np.stack([field*1.02, field, field*.94], -1)
    stream = io.BytesIO()
    Image.fromarray((rgb.clip(0, 1)*255).astype(np.uint8)).save(stream, format="PNG")
    return mjcf.Asset(stream.getvalue(), ".png", "concrete")


def infrastructure_texture(kind="cladding"):
    """Draw material detail in UV space; never a backdrop or a fly image."""
    rng = np.random.RandomState(91 if kind == "cladding" else 92)
    size = 1024
    base = rng.normal(106 if kind == "cladding" else 95, 2.2, (size, size))
    image = Image.fromarray(np.clip(base, 0, 255).astype(np.uint8)).convert("RGB")
    draw = ImageDraw.Draw(image)
    cols, rows = (4, 6) if kind == "cladding" else (4, 4)
    for row in range(rows):
        for col in range(cols):
            x0, y0 = col*size//cols+4, row*size//rows+4
            x1, y1 = (col+1)*size//cols-5, (row+1)*size//rows-5
            shade = int(rng.randint(88, 128))
            draw.rectangle((x0, y0, x1, y1), fill=(shade,)*3, outline=(37,)*3, width=3)
            draw.line((x0+4, y1-4, x0+4, y0+4, x1-4, y0+4), fill=(160,)*3, width=2)
            draw.line((x1-4, y0+4, x1-4, y1-4, x0+4, y1-4), fill=(61,)*3, width=2)
            for x in (x0+12, x1-12):
                for y in (y0+12, y1-12):
                    draw.ellipse((x-3, y-3, x+3, y+3), fill=(27,)*3)
                    draw.arc((x-3, y-3, x+3, y+3), 180, 300, fill=(180,)*3)
            if kind == "cladding":
                # Nested access panels, cooling slots, cable conduits and IDs.
                draw.rectangle((x0+20, y0+24, x1-22, y0+63), outline=(53,)*3, width=2)
                for x in range(x0+28, x1-30, 7):
                    draw.line((x, y0+32, x, y0+55), fill=(33,)*3, width=3)
                x = x0+int(rng.randint(25, 65))
                draw.line((x, y0+82, x, y1-22, x1-24, y1-22), fill=(43,)*3, width=5)
                draw.line((x+3, y0+82, x+3, y1-25, x1-24, y1-25), fill=(147,)*3, width=1)
                draw.text((x0+21, y1-17), f"N{row:02d}.{col:02d} // SERVICE", fill=(182,)*3)
                for _ in range(8):
                    xx = int(rng.randint(x0+8, x1-8))
                    yy = int(rng.randint(y0+8, y1-8))
                    draw.line((xx, yy, xx, min(y1-7, yy+int(rng.randint(10, 55)))),
                              fill=(shade-12,)*3)
            else:
                for y in range(y0+24, y1-15, 12):
                    for x in range(x0+25, x1-15, 24):
                        draw.line((x, y, x+7, y-4), fill=(shade+25,)*3, width=2)
                draw.rectangle((x0+22, y1-21, x1-22, y1-15), fill=(32,)*3)
    # Wear belongs to the surface coordinates, so it moves with each solid.
    pixels = np.asarray(image, dtype=float).copy()
    grain = rng.normal(0, 2.0, (size, size))
    for _ in range(150):
        x, y = rng.randint(0, size, 2)
        width, length = rng.randint(1, 5), rng.randint(12, 190)
        y1 = min(y+length, size)
        grain[y:y1, x:min(x+width, size)] -= np.linspace(rng.uniform(3, 16), 0, y1-y)[:, None]
    image = Image.fromarray(np.clip(pixels+grain[..., None], 0, 255).astype(np.uint8))
    stream = io.BytesIO()
    image.save(stream, format="PNG")
    return mjcf.Asset(stream.getvalue(), ".png", kind)


def designation_texture():
    """A physical wall designation, using the font already in the image."""
    image = Image.new("RGB", (1024, 256), (23, 25, 26))
    draw = ImageDraw.Draw(image)
    font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 70)
    small = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 23)
    draw.line((28, 25, 990, 25), fill=(165, 176, 176), width=3)
    draw.text((30, 55), "NETSPHERE", font=font, fill=(194, 206, 204))
    draw.text((36, 158), "SECTOR 09  /  ACCESS STRATUM 004", font=small, fill=(128, 147, 146))
    draw.line((30, 218, 680, 218), fill=(90, 108, 108), width=2)
    stream = io.BytesIO()
    image.save(stream, format="PNG")
    return mjcf.Asset(stream.getvalue(), ".png", "designation")


class City(composer.Arena):
    def _build(self, obstacle_shift=0.0, obstacles=True):
        super()._build(name="city")
        m = self._mjcf_root
        # Match the fly XML while attaching; final lighting is set afterwards.
        m.visual.headlight.set_attributes(
            ambient=[.4]*3, diffuse=[.8]*3, specular=[.1]*3)
        m.visual.map.set_attributes(znear=.002, zfar=100, fogstart=.30, fogend=1.6)
        m.visual.rgba.fog = [.035, .043, .047, 1]
        m.statistic.extent = 120
        m.asset.add("texture", name="void", type="skybox", builtin="gradient",
                    rgb1=[.015, .018, .022], rgb2=[.09, .10, .11], width=512, height=3072)
        surface_asset = concrete_texture()
        texture = m.asset.add("texture", name="cast_concrete", type="cube", file=surface_asset)
        floor_texture = m.asset.add("texture", name="floor_deck", type="2d",
                                    file=infrastructure_texture("deck"))
        panel_texture = m.asset.add("texture", name="infrastructure", type="cube",
                                    file=infrastructure_texture())
        m.asset.add("material", name="floor", texture=floor_texture, texuniform=True,
                    texrepeat=[.11, .11], rgba=[.70, .72, .73, 1], specular=.20, shininess=.25)
        for name, color in [
            ("concrete", [.68, .69, .70, 1]), ("edge", [.43, .44, .45, 1]),
            ("metal", [.21, .24, .25, 1]), ("pale", [.48, .49, .48, 1]),
        ]:
            mat = m.asset.add("material", name=name, rgba=color, specular=.12,
                              shininess=.18, reflectance=0)
            if name in ("concrete", "edge", "pale"):
                mat.set_attributes(texture=texture, texuniform=False)
            if name == "metal":
                mat.set_attributes(texture=panel_texture, texuniform=False)
        m.asset.add("material", name="cladding", texture=panel_texture,
                    rgba=[.68, .71, .73, 1], specular=.28, shininess=.30)
        designation = m.asset.add("texture", name="designation", type="2d",
                                  file=designation_texture())
        m.asset.add("material", name="designation", texture=designation,
                    rgba=[1, 1, 1, 1], emission=.25, specular=0)
        m.asset.add("material", name="lamp", rgba=[.86, .89, .84, 1], emission=.8)
        self.boxes = []
        self.cylinders = []
        self.capsules = []
        self.ground_z = -48.
        self._ground_geom = m.worldbody.add(
            "geom", name="groundplane", type="plane", size=[120, 120, 1],
            pos=[0, 0, self.ground_z], material="metal",
            contype=1, conaffinity=1, friction=[.8, .005, .0001])
        self.box("core", [0, 0, 39], [26, 15, 87], "concrete")
        self.box("wall_n", [0, 43, 60], [60, 2, 108])
        self.box("wall_s", [0, -43, 60], [60, 2, 108])
        self.box("wall_e", [60, 0, 60], [2, 45, 108])
        self.box("wall_w", [-60, 0, 60], [2, 45, 108])
        # Pilasters, recessed wall courses, service cabinets, upper galleries.
        for side in (-1, 1):
            # Thick courses and stacked modules stay part of the collidable world.
            for k, z in enumerate((-28, 0, 30, 64, 104, 148)):
                for j, x in enumerate((-48, -24, 0, 24, 48)):
                    self.box(f"armor_{side}_{k}_{j}", [x, side*40.8, z],
                             [10.5, .6+(j % 3)*.3, 11+(j % 2)*2], "concrete")
            for j, x in enumerate(np.arange(-54, 59, 8)):
                self.box(f"rib_{side}_{j}", [x, side*40.7, 56], [.55, .6, 104], "edge")
                self.box(f"panel_{side}_{j}", [x+2.5, side*40.9, 13],
                         [1.7, .25, 3.8], "metal")
            for k, z in enumerate((-34, -14, 11, 35, 62, 96, 132, 160)):
                self.box(f"course_{side}_{k}", [0, side*40.5, z],
                         [59, 1.3, .18], "pale")
            for j, x in enumerate((-45, -15, 15, 45)):
                self.box(f"light_{side}_{j}", [x, side*40.2, 10],
                         [.35, .10, .08], "lamp")
                m.worldbody.add("light", name=f"shaft_{side}_{j}",
                    pos=[x, side*37, 12], dir=[.1, -side*.25, -1],
                    diffuse=[.42, .29, .13], specular=[.05]*3,
                    attenuation=[1, .06, .004],
                    cutoff=65, exponent=2, directional=False, castshadow=False)
            # Surface labels are mapped onto actual wall-mounted solids.
            # Their depth is covered by the wall/rib collision envelope.
            label = self.box(f"designation_{side}", [-35, side*39.8, 7.8],
                             [5.5, 1.375, .08], "designation")
            label.euler = [side*np.pi/2, 0, 0]
            # The navigation envelope uses the resulting world-aligned box.
            self.boxes[-1] = ([-35, side*39.8, 7.8], [5.5, .08, 1.375])
        # Real shafts below the flight level, with overlapping suspended galleries.
        for j, (x, z) in enumerate(((-44, -8), (-12, 18), (20, 36), (49, 64),
                                     (-32, 92), (8, 118), (38, 148))):
            self.box(f"bridge_{j}", [x, 0, z], [1.25, 41, .45], "edge")
            for sign in (-1, 1):
                self.box(f"bridge_rail_{j}_{sign}", [x+sign*1.35, 0, z+1.5],
                         [.07, 41, .07], "metal")
            for k, y in enumerate((-36, -22, 22, 36)):
                self.box(f"bridge_post_{j}_{k}", [x-1.35, y, z+.8],
                         [.07, .07, .8], "metal")
        for side in (-1, 1):
            for j, z in enumerate((-24, -3, 24, 51, 84, 119)):
                self.box(f"ledge_{side}_{j}", [0, side*16.7, z],
                         [26.8, 1.7, .24], "edge")
            for j, x in enumerate((-21, -9, 4, 19)):
                self.box(f"core_buttress_{side}_{j}", [x, side*15.5, 35],
                         [.65, .6, 80], "edge")
        for j, y in enumerate((-11, -6, 0, 5, 11)):
            self.box(f"core_seam_{j}", [26.06, y, 18], [.07, .07, 18], "metal")
            self.box(f"core_seam_w_{j}", [-26.06, y, 18], [.07, .07, 18], "metal")
        # Obstacles intersect the nominal exploration route.
        if obstacles:
            for j, (x, y, radius, height) in enumerate([
                (-22, -28+obstacle_shift, 1.2, 13), (-2, -28, .9, 9),
                (20, -27, 1.4, 20), (43, -12, 1.3, 16),
                (42, 17, 1.6, 22), (20, 28, 1.5, 18),
                (-3, 28, 1.0, 14), (-24, 27, 1.4, 25),
                (-43, 11, 1.2, 15), (-43, -12, 1.5, 21),
            ]):
                self.cylinder(f"service_pillar_{j}", [x, y, height/2],
                              radius, height/2, "edge")
                self.cylinder(f"pillar_deep_{j}", [x, y, -24], radius, 24, "edge")
                self.cylinder(f"pillar_collar_{j}", [x, y, .5],
                              radius+.4, .5, "metal")
                for k, z in enumerate((height*.37, height*.70, height-.3)):
                    self.cylinder(f"pillar_band_{j}_{k}", [x, y, z],
                                  radius+.10, .10, "metal")
            # Low cross-pipes give the altitude controller useful obstacles.
            self.box("duct_s", [9, -33, 5.0], [1.0, 7.0, .6], "metal")
            self.box("duct_n", [-13, 33, 7.8], [1.0, 7.0, .6], "metal")
        rng = np.random.RandomState(25)
        for j in range(26):
            x = float(rng.uniform(-52, 52))
            y = float(rng.choice([-1, 1]) * rng.uniform(36, 39))
            self.cylinder(f"cable_{j}", [x, y, 41], .09+(j % 4)*.06, 86, "metal")
        # Sagging cables have capsule collision geometry, including their bends.
        for side in (-1, 1):
            for j, x in enumerate((-34, -7, 26)):
                for strand in range(2):
                    points = [[x+strand*.35, side*y, 16+j*12-7*np.sin(k*np.pi/4)]
                              for k, y in enumerate(np.linspace(17.8, 39, 5))]
                    for k in range(4):
                        self.capsule(f"sag_{side}_{j}_{strand}_{k}",
                                     points[k], points[k+1], .085, "metal")
            for j in range(8):
                x = -24+j*7
                self.cylinder(f"core_pipe_{side}_{j}", [x, side*16.2, 40],
                              .11+(j % 3)*.09, 80, "metal")
        m.worldbody.add("light", name="cold_upper_light", pos=[-20, 0, 155],
            dir=[.3, .2, -1], directional=True, diffuse=[.67, .78, .88],
            ambient=[.08, .10, .12], specular=[.05]*3, castshadow=True)
        m.worldbody.add("light", name="shaft_bounce", pos=[35, -15, 110],
            dir=[-.5, -.3, -1], directional=True, diffuse=[.20, .25, .28],
            specular=[0]*3, castshadow=False)
        self.box_centres = np.array([b[0] for b in self.boxes])
        self.box_halves = np.array([b[1] for b in self.boxes])
        self.cyl_data = np.array(self.cylinders)
        self.cap_data = np.array(self.capsules).reshape(-1, 7)

    def box(self, name, pos, size, material="concrete"):
        g = self._mjcf_root.worldbody.add(
            "geom", name=name, type="box", pos=pos, size=size,
            material=material, contype=1, conaffinity=1)
        self.boxes.append((pos, size))
        return g

    def cylinder(self, name, pos, radius, halfheight, material):
        g = self._mjcf_root.worldbody.add(
            "geom", name=name, type="cylinder", pos=pos, size=[radius, halfheight],
            material=material, contype=1, conaffinity=1)
        self.cylinders.append([*pos, radius, halfheight])
        return g

    def capsule(self, name, start, end, radius, material):
        g = self._mjcf_root.worldbody.add(
            "geom", name=name, type="capsule", fromto=[*start, *end], size=[radius],
            material=material, contype=1, conaffinity=1)
        self.capsules.append([*start, *end, radius])
        return g

    def clearance(self, points):
        """Signed point distance to the same primitive surfaces used by physics."""
        pts = np.asarray(points)
        shape = pts.shape[:-1]
        p = pts.reshape(-1, 3)
        # Core and ground provide a strict upper bound for broad-phase culling.
        core_q = np.abs(p-self.box_centres[0])-self.box_halves[0]
        core_d = np.linalg.norm(np.maximum(core_q, 0), axis=-1) + np.minimum(core_q.max(axis=-1), 0)
        ground_d = p[:, 2]-self.ground_z
        bound = max(float(np.minimum(core_d, ground_d).max()), .1)
        low, high = p.min(axis=0)-bound, p.max(axis=0)+bound
        keep = ((self.box_centres+self.box_halves >= low).all(axis=1)
                & (self.box_centres-self.box_halves <= high).all(axis=1))
        q = np.abs(p[:, None] - self.box_centres[None, keep]) - self.box_halves[None, keep]
        db = np.linalg.norm(np.maximum(q, 0), axis=-1) + np.minimum(np.max(q, axis=-1), 0)
        c = self.cyl_data
        if len(c):
            delta = p[:, None] - c[None, :, :3]
            q = np.stack([np.linalg.norm(delta[..., :2], axis=-1)-c[None, :, 3],
                          np.abs(delta[..., 2])-c[None, :, 4]], axis=-1)
            dc = np.linalg.norm(np.maximum(q, 0), axis=-1) + np.minimum(np.max(q, axis=-1), 0)
            result = np.minimum(db.min(axis=1, initial=np.inf), dc.min(axis=1))
        else:
            result = db.min(axis=1, initial=np.inf)
        c = self.cap_data
        if len(c):
            low_cap = np.minimum(c[:, :3], c[:, 3:6])-c[:, 6:7]
            high_cap = np.maximum(c[:, :3], c[:, 3:6])+c[:, 6:7]
            c = c[((high_cap >= low).all(axis=1) & (low_cap <= high).all(axis=1))]
            if len(c):
                ab = c[:, 3:6]-c[:, :3]
                delta = p[:, None]-c[None, :, :3]
                u = np.clip(np.sum(delta*ab[None], axis=-1)/np.sum(ab*ab, axis=-1), 0, 1)
                distance = np.linalg.norm(delta-u[..., None]*ab[None], axis=-1)-c[None, :, 6]
                result = np.minimum(result, distance.min(axis=1))
        return np.minimum(result, ground_d).reshape(shape)

    @property
    def ground_geoms(self):
        return (self._ground_geom,)

    def regenerate(self, random_state):
        pass

    def configure_visual(self):
        m = self._mjcf_root
        # The fly task overrides extent during attachment; apply world distances
        # afterwards so fog and clipping represent centimetres in this district.
        m.statistic.extent = 120
        m.visual.map.set_attributes(znear=.00003, zfar=5, fogstart=.16, fogend=1.15)
        m.visual.rgba.fog = [.25, .31, .36, 1]
        m.visual.headlight.set_attributes(
            ambient=[.29, .32, .35], diffuse=[.10, .12, .14], specular=[0]*3)
        getattr(m.visual, "global").set_attributes(offwidth=1280, offheight=720)
        m.visual.quality.set_attributes(shadowsize=4096, offsamples=4)
