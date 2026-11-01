const canvas = document.getElementById("scene-canvas");
const viewport = document.getElementById("scene-viewport");
const loading = document.getElementById("scene-loading");
const unavailable = document.getElementById("scene-unavailable");

if (canvas && viewport) {
  startScene();
}

async function startScene() {
  const module = await import("https://cdn.jsdelivr.net/npm/three@0.169.0/build/three.module.js").catch(() => null);
  if (!module) {
    loading?.classList.add("hidden");
    unavailable?.classList.remove("hidden");
    return;
  }

  const THREE = module;
  let renderer;
  try {
    renderer = new THREE.WebGLRenderer({ canvas, antialias: true, alpha: false, preserveDrawingBuffer: true });
  } catch {
    loading?.classList.add("hidden");
    unavailable?.classList.remove("hidden");
    return;
  }
  renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
  renderer.outputColorSpace = THREE.SRGBColorSpace;
  renderer.setClearColor(0x151a17, 1);

  const scene = new THREE.Scene();
  scene.background = new THREE.Color(0x151a17);
  const camera = new THREE.PerspectiveCamera(42, 1, 0.1, 100);
  const target = new THREE.Vector3(0, 1.15, 0);
  let theta = -0.75;
  let phi = 1.12;
  let distance = 10.5;
  const markers = new THREE.Group();
  scene.add(markers);

  scene.add(new THREE.HemisphereLight(0xdce6d7, 0x343a32, 2.2));
  const keyLight = new THREE.DirectionalLight(0xffedc4, 2.1);
  keyLight.position.set(-4, 8, 5);
  scene.add(keyLight);
  const fillLight = new THREE.DirectionalLight(0x94b0ac, 0.7);
  fillLight.position.set(6, 4, -4);
  scene.add(fillLight);

  const floor = new THREE.Mesh(
    new THREE.PlaneGeometry(10, 10),
    new THREE.MeshStandardMaterial({ color: 0x313832, roughness: 0.92, side: THREE.DoubleSide }),
  );
  floor.rotation.x = -Math.PI / 2;
  floor.position.y = -0.04;
  scene.add(floor);
  const grid = new THREE.GridHelper(10, 20, 0x829080, 0x515b50);
  grid.position.y = 0.01;
  grid.material.transparent = true;
  grid.material.opacity = 0.33;
  scene.add(grid);

  const wallMaterial = new THREE.MeshStandardMaterial({ color: 0x555d52, transparent: true, opacity: 0.42, side: THREE.DoubleSide, roughness: 1 });
  const backWall = new THREE.Mesh(new THREE.PlaneGeometry(10, 3.2), wallMaterial);
  backWall.position.set(0, 1.56, -5);
  scene.add(backWall);
  const leftWall = new THREE.Mesh(new THREE.PlaneGeometry(10, 3.2), wallMaterial);
  leftWall.rotation.y = Math.PI / 2;
  leftWall.position.set(-5, 1.56, 0);
  scene.add(leftWall);
  const axis = new THREE.AxesHelper(1.1);
  axis.position.set(-4.65, 0.03, 4.65);
  scene.add(axis);

  const raycaster = new THREE.Raycaster();
  const pointer = new THREE.Vector2();
  const markerMeshes = [];
  const pointerState = { down: false, moved: false, x: 0, y: 0, shift: false };

  function updateCamera() {
    const sinPhi = Math.sin(phi);
    camera.position.set(
      target.x + distance * sinPhi * Math.sin(theta),
      target.y + distance * Math.cos(phi),
      target.z + distance * sinPhi * Math.cos(theta),
    );
    camera.lookAt(target);
  }

  updateCamera();

  function labelSprite(text) {
    const contextCanvas = document.createElement("canvas");
    const context = contextCanvas.getContext("2d");
    context.font = "500 30px IBM Plex Mono, monospace";
    const width = Math.max(100, Math.ceil(context.measureText(text).width + 26));
    contextCanvas.width = width;
    contextCanvas.height = 54;
    context.font = "500 30px IBM Plex Mono, monospace";
    context.fillStyle = "rgba(18, 22, 19, .88)";
    context.fillRect(0, 0, width, 54);
    context.strokeStyle = "#d8a53d";
    context.strokeRect(1, 1, width - 2, 52);
    context.fillStyle = "#f0e9d8";
    context.textBaseline = "middle";
    context.fillText(text, 13, 27);
    const texture = new THREE.CanvasTexture(contextCanvas);
    texture.colorSpace = THREE.SRGBColorSpace;
    const sprite = new THREE.Sprite(new THREE.SpriteMaterial({ map: texture, transparent: true, depthTest: false }));
    sprite.scale.set(Math.max(0.75, width / 150), 0.42, 1);
    return sprite;
  }

  function updateMarkers(records) {
    while (markers.children.length) {
      const child = markers.children.pop();
      child.geometry?.dispose();
      child.material?.map?.dispose();
      child.material?.dispose();
    }
    markerMeshes.length = 0;
    records.forEach((record) => {
      const group = new THREE.Group();
      group.position.set(record.x, record.y, record.z);
      const sphere = new THREE.Mesh(
        new THREE.SphereGeometry(0.12, 18, 12),
        new THREE.MeshStandardMaterial({ color: 0xe8ad40, emissive: 0x6a4611, emissiveIntensity: 0.65, roughness: 0.4 }),
      );
      sphere.userData.marker = record;
      group.add(sphere);
      const stem = new THREE.Mesh(
        new THREE.CylinderGeometry(0.012, 0.012, 0.32, 6),
        new THREE.MeshBasicMaterial({ color: 0xe8ad40 }),
      );
      stem.position.y = 0.2;
      group.add(stem);
      const label = labelSprite(record.label || record.evidence_number);
      label.position.set(0, 0.52, 0);
      group.add(label);
      markers.add(group);
      markerMeshes.push(sphere);
    });
  }

  window.addEventListener("forensight:markers", (event) => updateMarkers(event.detail || []));
  window.updateForenSightMarkers = updateMarkers;

  function resize() {
    const width = Math.max(viewport.clientWidth, 1);
    const height = Math.max(viewport.clientHeight, 1);
    renderer.setSize(width, height, false);
    camera.aspect = width / height;
    camera.updateProjectionMatrix();
    if (viewport.clientWidth > 1 && viewport.clientHeight > 1) loading?.classList.add("hidden");
  }
  new ResizeObserver(resize).observe(viewport);
  window.addEventListener("resize", resize);
  resize();

  canvas.addEventListener("pointerdown", (event) => {
    pointerState.down = true;
    pointerState.moved = false;
    pointerState.x = event.clientX;
    pointerState.y = event.clientY;
    pointerState.shift = event.shiftKey;
    canvas.setPointerCapture(event.pointerId);
  });
  canvas.addEventListener("pointermove", (event) => {
    if (!pointerState.down) return;
    const dx = event.clientX - pointerState.x;
    const dy = event.clientY - pointerState.y;
    pointerState.x = event.clientX;
    pointerState.y = event.clientY;
    if (Math.abs(dx) + Math.abs(dy) > 2) pointerState.moved = true;
    if (pointerState.shift) {
      const right = new THREE.Vector3().setFromMatrixColumn(camera.matrix, 0);
      const up = new THREE.Vector3().setFromMatrixColumn(camera.matrix, 1);
      target.addScaledVector(right, -dx * distance * 0.0015);
      target.addScaledVector(up, dy * distance * 0.0015);
    } else {
      theta -= dx * 0.006;
      phi = Math.max(0.16, Math.min(Math.PI - 0.16, phi - dy * 0.006));
    }
    updateCamera();
  });
  canvas.addEventListener("pointerup", (event) => {
    pointerState.down = false;
    if (pointerState.moved) return;
    const bounds = canvas.getBoundingClientRect();
    pointer.x = ((event.clientX - bounds.left) / bounds.width) * 2 - 1;
    pointer.y = -((event.clientY - bounds.top) / bounds.height) * 2 + 1;
    raycaster.setFromCamera(pointer, camera);
    const selected = raycaster.intersectObjects(markerMeshes, false)[0]?.object.userData.marker;
    if (selected) {
      window.dispatchEvent(new CustomEvent("forensight:marker-selected", { detail: selected }));
    }
  });
  canvas.addEventListener("pointercancel", () => { pointerState.down = false; });
  canvas.addEventListener("wheel", (event) => {
    event.preventDefault();
    distance = Math.max(5.5, Math.min(20, distance + event.deltaY * 0.008));
    updateCamera();
  }, { passive: false });

  function render() {
    requestAnimationFrame(render);
    renderer.render(scene, camera);
  }
  render();
}