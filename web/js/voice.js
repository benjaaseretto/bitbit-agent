import * as THREE from "https://cdn.jsdelivr.net/npm/three@0.170.0/build/three.module.js";

function average(data, start, end) {
  let sum = 0;
  const slice = end - start;
  for (let i = start; i < end; i += 1) sum += data[i];
  return slice ? sum / slice / 255 : 0;
}

export function mountVoice(host) {
  const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
  const scene = new THREE.Scene();
  const camera = new THREE.PerspectiveCamera(38, 1, 0.1, 40);
  camera.position.z = 4.2;
  renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
  renderer.setClearColor(0x000000, 0);
  host.appendChild(renderer.domElement);
  Object.assign(renderer.domElement.style, { width: "100%", height: "100%", display: "block" });

  const root = new THREE.Group();
  scene.add(root);

  const cyan = new THREE.Color("#39e7ff");
  const magenta = new THREE.Color("#ff4ec8");

  const core = new THREE.Mesh(
    new THREE.IcosahedronGeometry(0.72, 1),
    new THREE.MeshBasicMaterial({
      color: cyan,
      wireframe: true,
      transparent: true,
      opacity: 0.95,
    }),
  );
  const glow = new THREE.Mesh(
    new THREE.IcosahedronGeometry(0.55, 2),
    new THREE.MeshBasicMaterial({
      color: magenta,
      transparent: true,
      opacity: 0.22,
      blending: THREE.AdditiveBlending,
      depthWrite: false,
    }),
  );
  const ringA = new THREE.Mesh(
    new THREE.TorusGeometry(1.15, 0.018, 8, 80),
    new THREE.MeshBasicMaterial({ color: cyan, transparent: true, opacity: 0.7 }),
  );
  const ringB = ringA.clone();
  ringB.rotation.x = Math.PI / 2.3;
  ringB.material = ringA.material.clone();
  ringB.material.color = magenta;
  root.add(core, glow, ringA, ringB);

  const count = 220;
  const positions = new Float32Array(count * 3);
  for (let i = 0; i < count; i += 1) {
    const r = 1.3 + Math.random() * 0.7;
    const theta = Math.random() * Math.PI * 2;
    const phi = Math.acos(2 * Math.random() - 1);
    positions[i * 3] = r * Math.sin(phi) * Math.cos(theta);
    positions[i * 3 + 1] = r * Math.cos(phi);
    positions[i * 3 + 2] = r * Math.sin(phi) * Math.sin(theta);
  }
  const pGeo = new THREE.BufferGeometry();
  pGeo.setAttribute("position", new THREE.BufferAttribute(positions, 3));
  const particles = new THREE.Points(
    pGeo,
    new THREE.PointsMaterial({
      color: cyan,
      size: 0.035,
      transparent: true,
      opacity: 0.7,
      blending: THREE.AdditiveBlending,
      depthWrite: false,
    }),
  );
  root.add(particles);

  let botEnergy = 0;
  let userEnergy = 0;
  let botAnalyser = null;
  let userAnalyser = null;
  const freq = new Uint8Array(64);
  const audioCtx = new AudioContext();

  const attach = (stream, kind) => {
    if (!stream) return;
    const source = audioCtx.createMediaStreamSource(stream);
    const analyser = audioCtx.createAnalyser();
    analyser.fftSize = 128;
    source.connect(analyser);
    if (kind === "bot") botAnalyser = analyser;
    else userAnalyser = analyser;
    if (audioCtx.state === "suspended") audioCtx.resume();
  };

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
  const tick = () => {
    if (disposed) return;
    if (botAnalyser) {
      botAnalyser.getByteFrequencyData(freq);
      botEnergy += (average(freq, 0, 12) - botEnergy) * 0.28;
    }
    if (userAnalyser) {
      userAnalyser.getByteFrequencyData(freq);
      userEnergy += (average(freq, 0, 12) - userEnergy) * 0.28;
    }
    const energy = Math.max(botEnergy, userEnergy);
    const scale = 1 + energy * 1.35;
    core.scale.setScalar(scale);
    glow.scale.setScalar(0.85 + energy * 1.8);
    glow.material.opacity = 0.16 + energy * 0.45;
    core.rotation.y += 0.01 + energy * 0.04;
    core.rotation.x += 0.006;
    ringA.rotation.z += 0.012 + userEnergy * 0.05;
    ringB.rotation.y += 0.01 + botEnergy * 0.05;
    particles.rotation.y -= 0.004;
    particles.material.size = 0.03 + energy * 0.06;
    renderer.render(scene, camera);
    requestAnimationFrame(tick);
  };
  requestAnimationFrame(tick);

  return {
    attachBot(stream) {
      attach(stream, "bot");
    },
    attachUser(stream) {
      attach(stream, "user");
    },
    dispose() {
      disposed = true;
      ro.disconnect();
      renderer.dispose();
      audioCtx.close();
      host.replaceChildren();
    },
  };
}
