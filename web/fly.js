import * as THREE from 'three';

// Rigid skinning: every surface vertex follows exactly one measured physical body.
// Seven material batches share one skeleton; no meshes are rebuilt per state.
export async function createFly(description, scene) {
  const response = await fetch(description.surface_url);
  if (!response.ok) throw new Error('The fly anatomy could not be loaded.');
  const binary = await response.arrayBuffer();
  if (binary.byteLength !== description.surface_bytes) throw new Error('Incomplete fly anatomy.');
  const hash = Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256', binary)),
    (byte) => byte.toString(16).padStart(2, '0')).join('');
  if (hash !== description.surface_sha256) throw new Error('Fly anatomy checksum mismatch.');
  const rig = new THREE.Group();
  const bones = description.bodies.map((name) => {
    const bone = new THREE.Bone();
    bone.name = name;
    rig.add(bone);
    return bone;
  });
  const skeleton = new THREE.Skeleton(bones, bones.map(() => new THREE.Matrix4()));
  const groups = new Map();
  for (const geom of description.geoms) {
    const key = geom.rgba.join(',');
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key).push(geom);
  }
  const meshes = [];
  for (const geoms of groups.values()) {
    const count = geoms.reduce((n, g) => n + description.meshes[g.mesh].vertex_count, 0);
    const indexCount = geoms.reduce((n, g) => n + description.meshes[g.mesh].index_count, 0);
    const positions = new Float32Array(count * 3);
    const indices = new Uint32Array(indexCount);
    const skinIndex = new Uint16Array(count * 4);
    const skinWeight = new Float32Array(count * 4);
    let vertexOffset = 0, indexOffset = 0;
    for (const geom of geoms) {
      const source = description.meshes[geom.mesh];
      positions.set(new Float32Array(binary, source.vertex_offset, source.vertex_count * 3), vertexOffset * 3);
      const sourceIndices = new Uint32Array(binary, source.index_offset, source.index_count);
      for (let i = 0; i < source.index_count; i++) indices[indexOffset + i] = sourceIndices[i] + vertexOffset;
      for (let i = vertexOffset; i < vertexOffset + source.vertex_count; i++) {
        skinIndex[i * 4] = geom.body;
        skinWeight[i * 4] = 1;
      }
      vertexOffset += source.vertex_count;
      indexOffset += source.index_count;
    }
    const geometry = new THREE.BufferGeometry();
    geometry.setAttribute('position', new THREE.BufferAttribute(positions, 3));
    geometry.setAttribute('skinIndex', new THREE.BufferAttribute(skinIndex, 4));
    geometry.setAttribute('skinWeight', new THREE.BufferAttribute(skinWeight, 4));
    geometry.setIndex(new THREE.BufferAttribute(indices, 1));
    geometry.computeVertexNormals();
    const [r, g, b, a] = geoms[0].rgba;
    const material = new THREE.MeshStandardMaterial({
      color: new THREE.Color(r, g, b), roughness: .65, metalness: .02,
      transparent: a < 1, opacity: a, depthWrite: a === 1,
      side: a < 1 ? THREE.DoubleSide : THREE.FrontSide,
    });
    const mesh = new THREE.SkinnedMesh(geometry, material);
    mesh.bind(skeleton, new THREE.Matrix4());
    mesh.frustumCulled = false; // Visibility is bounded by projected animal size below.
    meshes.push(mesh);
    rig.add(mesh);
  }
  rig.visible = false;
  scene.add(rig);
  const position = new THREE.Vector3();
  const bytes = new Uint8Array(bones.length * 7 * 4);
  const poses = new Float32Array(bytes.buffer);
  let revision = -1;
  return {
    position,
    headPosition: bones[description.bodies.indexOf('head')].position,
    get revision() { return revision; },
    get visible() { return rig.visible; },
    apply(state) {
      if (!state.poses_b64 || state.pose_revision === revision) return false;
      const decoded = atob(state.poses_b64);
      if (decoded.length !== bytes.length) throw new Error('Invalid physical pose packet.');
      for (let i = 0; i < bytes.length; i++) bytes[i] = decoded.charCodeAt(i);
      for (let i = 0; i < bones.length; i++) {
        const o = i * 7;
        bones[i].position.fromArray(poses, o);
        bones[i].quaternion.set(poses[o + 4], poses[o + 5], poses[o + 6], poses[o + 3]);
      }
      position.copy(bones[description.focus_body].position);
      revision = state.pose_revision;
      return true;
    },
    updateVisibility(camera, height) {
      const pixels = .3 * height / (2 * camera.position.distanceTo(position) *
        Math.tan(THREE.MathUtils.degToRad(camera.fov / 2)));
      rig.visible = revision >= 0 && pixels >= 8;
    },
  };
}
