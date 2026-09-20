import * as THREE from "https://cdn.jsdelivr.net/npm/three@0.170.0/build/three.module.js";

function latLonToVec3(lat, lon, radius) {
  const phi = ((90 - lat) * Math.PI) / 180;
  const theta = ((lon + 180) * Math.PI) / 180;
  return new THREE.Vector3(
    -radius * Math.sin(phi) * Math.cos(theta),
    radius * Math.cos(phi),
    radius * Math.sin(phi) * Math.sin(theta),
  );
}

function makeArc(from, to, color) {
  const mid = from.clone().add(to).multiplyScalar(0.5);
  mid.normalize().multiplyScalar(from.length() * 1.28);
  const curve = new THREE.QuadraticBezierCurve3(from, mid, to);
  const geometry = new THREE.BufferGeometry().setFromPoints(curve.getPoints(48));
  const material = new THREE.LineBasicMaterial({
    color,
    transparent: true,
    opacity: 0.55,
    blending: THREE.AdditiveBlending,
    depthWrite: false,
  });
  return new THREE.Line(geometry, material);
}

export function mountGlobe(host, { ambient = false } = {}) {
  const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  const renderer = new THREE.WebGLRenderer({
    antialias: !ambient,
    alpha: true,
    powerPreference: ambient ? "low-power" : "high-performance",
  });
  const scene = new THREE.Scene();
  const camera = new THREE.PerspectiveCamera(42, 1, 0.1, 100);
  camera.position.set(0, 0.35, 4.4);
  renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, ambient ? 1.5 : 2));
  renderer.setClearColor(0x000000, 0);
  host.appendChild(renderer.domElement);
  Object.assign(renderer.domElement.style, {
    width: "100%",
    height: "100%",
    display: "block",
  });

  const root = new THREE.Group();
  root.rotation.y = THREE.MathUtils.degToRad(-55);
  root.rotation.x = THREE.MathUtils.degToRad(12);
  scene.add(root);

  const neon = new THREE.Color("#2dd4bf");
  const R = 1.55;

  root.add(
    new THREE.Mesh(
      new THREE.SphereGeometry(R * 1.08, ambient ? 32 : 48, ambient ? 32 : 48),
      new THREE.MeshBasicMaterial({
        color: neon,
        transparent: true,
        opacity: 0.06,
        side: THREE.BackSide,
        depthWrite: false,
      }),
    ),
  );
  root.add(
    new THREE.Mesh(
      new THREE.SphereGeometry(R, ambient ? 28 : 36, ambient ? 20 : 28),
      new THREE.MeshBasicMaterial({
        color: neon,
        wireframe: true,
        transparent: true,
        opacity: ambient ? 0.18 : 0.22,
      }),
    ),
  );

  const shells = new THREE.Group();
  for (const [radius, opacity] of [
    [R * 1.02, 0.14],
    [R * 1.14, 0.08],
    [R * 1.28, 0.05],
  ]) {
    shells.add(
      new THREE.Mesh(
        new THREE.SphereGeometry(radius, ambient ? 20 : 28, ambient ? 14 : 18),
        new THREE.MeshBasicMaterial({
          color: 0xffffff,
          wireframe: true,
          transparent: true,
          opacity,
        }),
      ),
    );
  }
  root.add(shells);

  const gridMat = new THREE.LineBasicMaterial({
    color: neon,
    transparent: true,
    opacity: ambient ? 0.14 : 0.18,
    blending: THREE.AdditiveBlending,
    depthWrite: false,
  });
  const grid = new THREE.Group();
  for (let lat = -60; lat <= 60; lat += ambient ? 30 : 20) {
    const pts = [];
    for (let lon = -180; lon <= 180; lon += 6) pts.push(latLonToVec3(lat, lon, R * 1.001));
    grid.add(new THREE.Line(new THREE.BufferGeometry().setFromPoints(pts), gridMat));
  }
  for (let lon = -180; lon < 180; lon += ambient ? 45 : 30) {
    const pts = [];
    for (let lat = -80; lat <= 80; lat += 4) pts.push(latLonToVec3(lat, lon, R * 1.001));
    grid.add(new THREE.Line(new THREE.BufferGeometry().setFromPoints(pts), gridMat));
  }
  root.add(grid);

  const hubs = [
    [-25.3, -57.6],
    [-34.6, -58.4],
    [-23.5, -46.6],
    [40.7, -74.0],
    [51.5, -0.1],
    [35.7, 139.7],
    [-33.9, 18.4],
    [1.3, 103.8],
    [19.4, -99.1],
    [25.2, 55.3],
  ];
  const nodes = new THREE.Group();
  const arcs = new THREE.Group();
  const hubVecs = hubs.map(([lat, lon]) => latLonToVec3(lat, lon, R * 1.01));
  for (const v of hubVecs) {
    const dot = new THREE.Mesh(
      new THREE.SphereGeometry(0.028, 10, 10),
      new THREE.MeshBasicMaterial({ color: neon, transparent: true, opacity: 0.95 }),
    );
    dot.position.copy(v);
    nodes.add(dot);
  }
  for (let i = 0; i < hubVecs.length; i += 1) {
    arcs.add(makeArc(hubVecs[i], hubVecs[(i + 3) % hubVecs.length], neon));
  }
  for (const idx of [1, 2, 3, 8]) arcs.add(makeArc(hubVecs[0], hubVecs[idx], neon));
  root.add(nodes, arcs);

  const particleCount = ambient ? 180 : 420;
  const positions = new Float32Array(particleCount * 3);
  for (let i = 0; i < particleCount; i += 1) {
    const r = R * (1.15 + Math.random() * 0.55);
    const theta = Math.random() * Math.PI * 2;
    const phi = Math.acos(2 * Math.random() - 1);
    positions[i * 3] = r * Math.sin(phi) * Math.cos(theta);
    positions[i * 3 + 1] = r * Math.cos(phi);
    positions[i * 3 + 2] = r * Math.sin(phi) * Math.sin(theta);
  }
  const particleGeo = new THREE.BufferGeometry();
  particleGeo.setAttribute("position", new THREE.BufferAttribute(positions, 3));
  const particles = new THREE.Points(
    particleGeo,
    new THREE.PointsMaterial({
      color: neon,
      size: 0.018,
      transparent: true,
      opacity: ambient ? 0.42 : 0.55,
      depthWrite: false,
      blending: THREE.AdditiveBlending,
      sizeAttenuation: true,
    }),
  );
  root.add(particles);

  const disc = new THREE.Mesh(
    new THREE.RingGeometry(R * 1.05, R * 1.55, ambient ? 64 : 96),
    new THREE.MeshBasicMaterial({
      color: neon,
      transparent: true,
      opacity: 0.12,
      side: THREE.DoubleSide,
      blending: THREE.AdditiveBlending,
      depthWrite: false,
    }),
  );
  disc.rotation.x = Math.PI / 2;
  disc.position.y = -0.15;
  root.add(disc);

  const accent = new THREE.Mesh(
    new THREE.TorusGeometry(R * 1.22, 0.008, 8, ambient ? 80 : 120),
    new THREE.MeshBasicMaterial({ color: neon, transparent: true, opacity: 0.35 }),
  );
  accent.rotation.x = Math.PI / 2.4;
  accent.rotation.z = 0.35;
  root.add(accent);

  const resize = () => {
    const w = Math.max(1, host.clientWidth);
    const h = Math.max(1, host.clientHeight);
    camera.aspect = w / h;
    camera.updateProjectionMatrix();
    renderer.setSize(w, h, false);
  };
  resize();
  const ro = new ResizeObserver(resize);
  ro.observe(host);

  let disposed = false;
  const clock = new THREE.Clock();
  let rotSpeed = ambient ? 0.0009 : 0.0016;
  const tick = () => {
    if (disposed) return;
    const t = clock.getElapsedTime();
    if (!reduceMotion) {
      root.rotation.y += rotSpeed;
      shells.rotation.y -= rotSpeed * 0.44;
      particles.rotation.y += rotSpeed * 0.56;
      accent.rotation.z = 0.35 + Math.sin(t * 0.35) * 0.08;
      disc.rotation.z = t * 0.08;
    }
    renderer.render(scene, camera);
    requestAnimationFrame(tick);
  };
  requestAnimationFrame(tick);

  return {
    setAmbient(value) {
      rotSpeed = value ? 0.0009 : 0.0016;
    },
    dispose() {
      disposed = true;
      ro.disconnect();
      renderer.dispose();
      host.replaceChildren();
    },
  };
}
