// 説明用の模型。箱だけをコードで作る。水は決めた段の高さへ動かすだけで、シミュレーションはしない。
import * as THREE from "three";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";
import { CSS2DObject, CSS2DRenderer } from "three/addons/renderers/CSS2DRenderer.js";

const WIDTH = 20;
const DEPTH = 16;
const FLOOR_H = 3.2;
const BASE_Y = -3.4;
const COLORS = {
  room: 0xdfe3e8,
  key: 0xbcd0e5,
  tr: 0xc9c2d6,
  trUnknown: 0xa89bc4,
  stopped: 0xe8853a,
  water: 0x3f87c7,
  ground: 0xcfd3cc,
  road: 0x9a9da3,
  ghost: 0xb9c3cf,
  panel: 0x4f6d8f,
  conduit: 0x5b5f66,
};
const NO_HEIGHT_NOTE = "高さは未確認";
// 主な部屋。札の1行目に判定の札と確かめる人の印を出し、図面で確かめるまで破線の箱にする（F-041）。
const MAIN_ROOMS = ["elec", "tr", "pump", "panel_room", "tank", "gen"];
// 部屋と「何が止まるか」の行の対応。判定はサーバーが返した行の札だけを読む。
const ROOM_ROWS = { elec: "power", panel_room: "power", pump: "water", tr: "tr", tank: "tank", gen: "gen" };
const RAISED_PANEL_NOTE = "ポンプのスイッチ盤（付け替え後）\n付け替える高さは見積りと現地調査で決める";
const BEFORE_RAISE_NAME = "付け替える前の盤";

let renderer, labels, scene, camera, controls, group;
let meshes = {};
let waters = [];
let focusPoints = {};
let detailLabels = [];
let directionGroup = null;
let targetCam = null;
let targetLook = null;
let raf = null;
let roomTags = {};
let panelLabel = null;
let ghostPanel = null;
let focusKey = null;
let raisedNow = false;

function box(w, h, d, color, opacity = 1) {
  const material = new THREE.MeshStandardMaterial({ color, transparent: opacity < 1, opacity, roughness: 0.85 });
  const mesh = new THREE.Mesh(new THREE.BoxGeometry(w, h, d), material);
  return mesh;
}

function edges(mesh, color = 0x333333, dashed = false) {
  const geometry = new THREE.EdgesGeometry(mesh.geometry);
  const material = dashed
    ? new THREE.LineDashedMaterial({ color, dashSize: 0.35, gapSize: 0.25 })
    : new THREE.LineBasicMaterial({ color });
  const line = new THREE.LineSegments(geometry, material);
  if (dashed) line.computeLineDistances();
  mesh.add(line);
}

// extra.head は札の1行目に置く要素。extra.always は焦点に関係なく出す条件、extra.hide は隠す条件。
function label(text, position, className = "model-label", detailOf = null, extra = {}) {
  const node = document.createElement("div");
  node.className = className;
  if (extra.head) node.append(extra.head, `\n${text}`);
  else node.textContent = text;
  const object = new CSS2DObject(node);
  object.position.copy(position);
  group.add(object);
  if (detailOf) {
    detailLabels.push({ object, detailOf, always: extra.always, hide: extra.hide });
    object.visible = detailVisible(detailLabels[detailLabels.length - 1]);
  }
  return object;
}

function detailVisible(item) {
  return (item.detailOf === focusKey || Boolean(item.always && item.always())) && !(item.hide && item.hide());
}

function refreshDetails() {
  detailLabels.forEach((item) => {
    item.object.visible = detailVisible(item);
  });
}

// 部屋の札の1行目：判定の札（三分類）と、確かめる人の印。印と色は平面図の WHO_LABELS と同じ。
function roomVerdict(key) {
  const rows = window.App?.building?.equipment || [];
  const row = rows.find((item) => item.key === ROOM_ROWS[key]);
  return row ? { verdict: row.verdict, label: row.verdict_label } : { verdict: "unconfirmed", label: "未確認（調査が必要）" };
}

function fillRoomTag(head, key, sample) {
  const { verdict, label: verdictLabel } = roomVerdict(key);
  const tag = document.createElement("span");
  tag.className = `model-tag tag-${verdict}`;
  tag.textContent = verdictLabel;
  head.replaceChildren(tag);
  const pin = (sample.pins || []).find((item) => item.target === key);
  const whoLabels = window.WHO_LABELS || {};
  if (pin && whoLabels[pin.who_kind]) {
    const who = document.createElement("span");
    who.className = `model-who who-${pin.who_kind}`;
    who.textContent = whoLabels[pin.who_kind];
    head.append(who);
  }
}

function roomAbsent(sample, key) {
  return (sample.confirmedRooms || []).includes(`absent:${key}`);
}

// 盤の下の端の高さ。F-024 の入力（answers.heights.panel_bottom = { cm, source }）があるときだけその値を出す。
// 入れた値をそのまま出すだけで、浸かる・浸からないは計算しない。
function panelHeightNote(sample) {
  const input = sample.answers?.heights?.panel_bottom;
  if (!input || input.cm === null || input.cm === undefined || input.cm === "") return NO_HEIGHT_NOTE;
  // 出どころの語は、サーバーの水の行（app/building.py の HEIGHT_SOURCES）と同じ言い方にする。
  const source = { drawing: "竣工図", measured: "実測", hearing: "聞き取り" }[input.source] || input.source || "出どころ未選択";
  return `入力値：床から ${input.cm}cm（${source}）`;
}

function placeRoom(room, baseY, height) {
  const w = room.w * WIDTH;
  const d = room.h * DEPTH;
  return {
    center: new THREE.Vector3(room.x * WIDTH + w / 2 - WIDTH / 2, baseY + height / 2, room.y * DEPTH + d / 2 - DEPTH / 2),
    w,
    d,
    h: height,
  };
}

function addWater(key, place) {
  const mesh = box(Math.max(place.w - 0.2, 0.2), 1, Math.max(place.d - 0.2, 0.2), COLORS.water, 0.55);
  mesh.position.set(place.center.x, place.center.y - place.h / 2, place.center.z);
  mesh.scale.y = 0.001;
  group.add(mesh);
  waters.push({ key, mesh, baseY: place.center.y - place.h / 2, room: place, level: 0, target: 0 });
}

function roomKindColor(key) {
  if (key === "tr") return COLORS.tr;
  return ["elec", "pump", "panel_room", "tank", "gen"].includes(key) ? COLORS.key : COLORS.room;
}

function buildRooms(sample) {
  const views = sample.views;
  views.forEach((view) => {
    const basement = view.name.includes("地下");
    const isGround = view.name.startsWith("1階");
    if (!basement && !isGround) return;
    const baseY = basement ? BASE_Y : 0;
    const height = basement ? -BASE_Y - 0.2 : FLOOR_H - 0.2;
    view.rooms.forEach((room) => {
      if (room.key === "soil" || room.key === "garden") return;
      const place = placeRoom(room, baseY, height);
      const closed = room.key === "tr";
      const main = MAIN_ROOMS.includes(room.key);
      const opacity = closed ? 0.9 : isGround && sample.archetype !== "ground" ? 0.12 : 0.28;
      const mesh = box(place.w - 0.1, place.h, place.d - 0.1, roomKindColor(room.key), opacity);
      mesh.position.copy(place.center);
      // 主な部屋は、図面で確かめるまで破線の箱にする。
      edges(mesh, 0x444444, main && !sample.confirmedRooms.includes(room.key));
      group.add(mesh);
      meshes[room.key] = mesh;
      focusPoints[room.key] = { look: place.center.clone(), from: place.center.clone().add(new THREE.Vector3(7, 5, 14)) };
      // 図面で「なし」と確かめた箱だけ消す。ほかの部品が位置を使うので、箱は作って見えなくする。
      if (main && roomAbsent(sample, room.key)) {
        mesh.visible = false;
        return;
      }
      if (main) {
        const trUnseen = room.key === "tr" && ["no", "unknown"].includes(sample.answers?.tr);
        const name = trUnseen ? "東京電力の設備\n位置は未確認" : room.key === "tr" ? "東京電力の変圧器の部屋" : window.App.roomName(room.key);
        const note = sample.confirmedRooms.includes(room.key) || trUnseen ? name : `${name}\n位置は図面で未確認`;
        // 隣り合う部屋の札が重ならないよう、借室は上へ、電気室は左へずらす。
        const shift = { tr: [0, 2.4], elec: [-3.8, 0.25], panel_room: [-3.8, 0.25] }[room.key] || [0, 0.25];
        const head = document.createElement("span");
        head.className = "model-tag-line";
        fillRoomTag(head, room.key, sample);
        roomTags[room.key] = head;
        label(note, place.center.clone().add(new THREE.Vector3(shift[0], place.h / 2 + shift[1], 0)), "model-label", null, { head });
      }
      if (room.key === "tr" && !["no", "unknown"].includes(sample.answers?.tr)) {
        const hidden = sample.confirmedRooms.includes("tr") ? "中は建物側から分からない" : "中は建物側から分からない\n位置は図面で未確認";
        label(hidden, place.center.clone(), "model-label model-label-small", "tr");
      }
      if (room.key === "park" || room.key === "slope") {
        label(window.App.roomName(room.key), place.center.clone(), "model-label model-label-small", room.key);
      }
      const wetRoom = basement || (sample.archetype === "ground" && ["panel_room", "pump", "tr", "hall"].includes(room.key));
      // 借室の中は描かない。水も箱の中には出さず、箱の色で示す。
      if (wetRoom && !["ev", "stair", "tr"].includes(room.key)) addWater(room.key, place);
    });
  });
}

function buildEquipment(sample) {
  const add = (key, roomKey, offset, size, name, detailOf, extra = {}) => {
    const room = meshes[roomKey];
    if (!room || !room.visible) return null;
    const mesh = box(size[0], size[1], size[2], COLORS.panel);
    mesh.position.copy(room.position).add(offset);
    edges(mesh);
    group.add(mesh);
    meshes[key] = mesh;
    if (!name) return null;
    return label(`${name}\n${extra.note || NO_HEIGHT_NOTE}`, mesh.position.clone().add(new THREE.Vector3(0, size[1] / 2 + 0.2, 0)), "model-label model-label-small", detailOf, extra);
  };
  const pumpRoom = meshes.pump;
  if (pumpRoom && pumpRoom.visible) {
    const roomDepth = pumpRoom.geometry.parameters.depth;
    // 盤を付け替えたときは、札を付け替え後の文に替える（F-040）。札はほかの盤と同じく、ポンプの部屋を見たときに出す。
    panelLabel = add("panel", "pump", new THREE.Vector3(-0.3, 0, -roomDepth / 2 + 0.25), [1.1, 1.1, 0.35], "ポンプのスイッチ盤", "pump", { note: panelHeightNote(sample) });
    add("pump_unit", "pump", new THREE.Vector3(0.8, -pumpRoom.geometry.parameters.height / 2 + 0.85, 0.8), [1.3, 0.9, 1.1], null);
    if (meshes.panel) {
      // 付け替える前の位置に、破線の輪郭の箱と札を残す。付け替えたときだけ出す。
      ghostPanel = box(1.1, 1.1, 0.35, COLORS.ghost, 0.08);
      ghostPanel.position.copy(meshes.panel.position);
      edges(ghostPanel, 0x4f6d8f, true);
      ghostPanel.visible = false;
      group.add(ghostPanel);
      label(`${BEFORE_RAISE_NAME}\n${panelHeightNote(sample)}`, ghostPanel.position.clone().add(new THREE.Vector3(-2.8, -0.9, 0.3)), "model-label model-label-small model-label-ghost", "pump", { hide: () => !raisedNow });
    }
  }
  if (meshes.elec) add("hv", "elec", new THREE.Vector3(0, -meshes.elec.geometry.parameters.height / 2 + 1.4, 0), [2.2, 1.7, 1.2], "受電の箱", "elec");
  if (meshes.panel_room) add("hv", "panel_room", new THREE.Vector3(0, 0, -meshes.panel_room.geometry.parameters.depth / 2 + 0.3), [1.5, 1.4, 0.4], "おおもとのスイッチ盤", "panel_room");
}

function buildElevator(sample) {
  const key = meshes.ev ? "ev" : meshes.ev_1f ? "ev_1f" : null;
  if (!key) return;
  const shaft = meshes[key];
  const bottomY = sample.archetype === "ground" ? -1.2 : BASE_Y - 1;
  const height = FLOOR_H * 2 - bottomY;
  const mesh = box(shaft.geometry.parameters.width, height, shaft.geometry.parameters.depth, COLORS.key, 0.35);
  mesh.position.set(shaft.position.x, bottomY + height / 2, shaft.position.z);
  edges(mesh);
  group.add(mesh);
  group.remove(shaft);
  meshes.ev = mesh;
  const pitPlace = { center: new THREE.Vector3(shaft.position.x, bottomY + 0.4, shaft.position.z), w: shaft.geometry.parameters.width, d: shaft.geometry.parameters.depth, h: 0.8 };
  addWater("ev", pitPlace);
  focusPoints.ev = { look: pitPlace.center.clone(), from: pitPlace.center.clone().add(new THREE.Vector3(5, 3, 8)) };
  label("エレベーターの底の部分", pitPlace.center.clone().add(new THREE.Vector3(0, 1, 0)), "model-label model-label-small", "ev");
}

function buildOutside(sample) {
  const ground = box(WIDTH + 14, 0.1, DEPTH + 12, COLORS.ground, 0.1);
  ground.position.set(0, -0.05, 1);
  group.add(ground);
  const road = box(WIDTH + 14, 0.08, 4, COLORS.road, 0.35);
  road.position.set(0, 0.02, DEPTH / 2 + 4.8);
  group.add(road);
  focusPoints.road = { look: road.position.clone(), from: road.position.clone().add(new THREE.Vector3(0, 6, 12)) };
  const roadWater = { center: new THREE.Vector3(0, 0.05, DEPTH / 2 + 4.8), w: WIDTH + 14, d: 4, h: 1 };
  addWater("road", roadWater);
  label("前の道路", road.position.clone().add(new THREE.Vector3(9, 0.5, 0)), "model-label model-label-small");

  if (sample.underground_feed) {
    const elec = meshes.elec;
    const cover = box(1.2, 0.12, 1.2, COLORS.conduit);
    const x = elec ? elec.position.x - 1.5 : -6;
    cover.position.set(x, 0.1, DEPTH / 2 + 2);
    group.add(cover);
    meshes.hh = cover;
    focusPoints.hh = { look: cover.position.clone(), from: cover.position.clone().add(new THREE.Vector3(3, 5, 7)) };
    label("歩道ぎわの「東電」「高圧」の蓋（開けない）", cover.position.clone().add(new THREE.Vector3(0, 0.6, 0)), "model-label model-label-small", "hh");
    const startZ = elec ? elec.position.z + elec.geometry.parameters.depth / 2 : 0;
    const conduit = box(0.35, 0.35, DEPTH / 2 + 2 - startZ, COLORS.conduit);
    conduit.position.set(x, BASE_Y + 1.2, (startZ + DEPTH / 2 + 2) / 2);
    group.add(conduit);
    const riser = box(0.35, -BASE_Y - 1.2, 0.35, COLORS.conduit);
    riser.position.set(x, (BASE_Y + 1.2) / 2, DEPTH / 2 + 2);
    group.add(riser);
    label("地中の電線の管", conduit.position.clone().add(new THREE.Vector3(-1.6, 0.4, 0)), "model-label model-label-small", "elec");
    const hole = box(0.5, 0.5, 0.2, 0xd9534f);
    hole.position.set(x, BASE_Y + 1.2, startZ);
    group.add(hole);
    meshes.hole = hole;
  }
  if (sample.archetype === "ground" && meshes.panel_room) {
    const door = box(1.6, 0.5, 0.2, COLORS.panel);
    const room = meshes.panel_room;
    door.position.set(room.position.x, 0.25, DEPTH / 2);
    group.add(door);
    focusPoints.door = { look: door.position.clone(), from: door.position.clone().add(new THREE.Vector3(2, 3, 8)) };
    label("坂の下の側の扉と足元の換気口", door.position.clone().add(new THREE.Vector3(0, 0.7, 0.3)), "model-label model-label-small");
  }
  if (meshes.slope) {
    const slope = meshes.slope;
    const ramp = box(slope.geometry.parameters.width * 0.8, 0.2, slope.geometry.parameters.depth * 1.15, 0x8c8f94);
    ramp.position.set(slope.position.x, BASE_Y / 2, slope.position.z);
    ramp.rotation.x = -Math.atan2(-BASE_Y, slope.geometry.parameters.depth * 1.15);
    group.add(ramp);
    focusPoints.slope = { look: ramp.position.clone(), from: ramp.position.clone().add(new THREE.Vector3(4, 6, 9)) };
  }
  if (sample.archetype === "tower" && meshes.tank) {
    const basin = box(0.9, 0.12, 0.9, COLORS.conduit);
    basin.position.set(meshes.tank.position.x, 0.1, meshes.tank.position.z);
    group.add(basin);
    label("敷地の雨水ます", basin.position.clone().add(new THREE.Vector3(0, 0.6, 0)), "model-label model-label-small");
    const pipe = box(0.3, -BASE_Y, 0.3, COLORS.conduit);
    pipe.position.set(basin.position.x, BASE_Y / 2, basin.position.z);
    group.add(pipe);
  }
}

function buildUpper(sample) {
  const levels = Math.min(sample.floors - 1, sample.archetype === "tower" ? 16 : 7);
  const height = levels * FLOOR_H;
  const footprintW = sample.archetype === "tower" ? WIDTH * 0.62 : WIDTH;
  const footprintD = sample.archetype === "tower" ? DEPTH * 0.62 : DEPTH;
  const mesh = box(footprintW, height, footprintD, COLORS.ghost, 0.05);
  mesh.position.set(0, FLOOR_H + height / 2, 0);
  edges(mesh, 0x8a94a0);
  for (let i = 1; i < levels; i += 1) {
    const slab = box(footprintW, 0.03, footprintD, COLORS.ghost, 0.18);
    slab.position.set(0, FLOOR_H + i * FLOOR_H, 0);
    group.add(slab);
  }
  group.add(mesh);
  label(`上の階は省略（全${sample.floors}階建て）`, new THREE.Vector3(footprintW / 2 + 1, FLOOR_H + Math.min(height, 12) - 1, 0), "model-label model-label-small");
}

function buildPins(sample) {
  sample.pins.forEach((pin) => {
    const point = focusPoints[pin.focus];
    if (!point) return;
    const node = document.createElement("button");
    node.type = "button";
    node.className = `model-pin who-${pin.who_kind}`;
    node.textContent = pin.key;
    node.title = pin.title;
    node.addEventListener("click", () => window.App.selectPin(pin.key));
    const object = new CSS2DObject(node);
    object.position.copy(point.look).add(new THREE.Vector3(0, 0.3, 0));
    group.add(object);
  });
}

function clear() {
  if (group) {
    const remove = [];
    group.traverse((child) => {
      if (child.isCSS2DObject) remove.push(child);
    });
    remove.forEach((child) => child.element.remove());
    scene.remove(group);
  }
  group = new THREE.Group();
  scene.add(group);
  meshes = {};
  waters = [];
  focusPoints = {};
  detailLabels = [];
  directionGroup = null;
  roomTags = {};
  panelLabel = null;
  ghostPanel = null;
  focusKey = null;
  raisedNow = false;
}

function waterTarget(item, level, measure, sample) {
  if (item.key === "road") return level >= 3 ? 0.6 : level >= 1 ? 0.3 : 0;
  if (item.key === "ev") return level >= 2 ? 0.8 : 0;
  if (item.key === "tr" && level < 3) return 0;
  if ((item.key === "elec" || item.key === "panel_room") && measure === "hole") return 0;
  if (sample.archetype === "ground") return level >= 3 ? 1.1 : 0;
  if (level === 1) return 0;
  return level === 2 ? 0.3 : 1.3;
}

function setColor(mesh, color) {
  if (mesh && mesh.material) mesh.material.color.setHex(color);
}

function loop() {
  raf = requestAnimationFrame(loop);
  tick();
}

function tick() {
  if (targetCam) {
    camera.position.lerp(targetCam, 0.07);
    controls.target.lerp(targetLook, 0.07);
    if (camera.position.distanceTo(targetCam) < 0.05) targetCam = null;
  }
  waters.forEach((item) => {
    item.level += (item.target - item.level) * 0.08;
    const value = Math.max(item.level, 0.001);
    item.mesh.scale.y = value;
    item.mesh.position.y = item.baseY + value / 2;
    item.mesh.visible = item.level > 0.01;
  });
  controls.update();
  renderer.render(scene, camera);
  labels.render(scene, camera);
}

function resize() {
  const container = document.getElementById("model-view");
  const width = container.clientWidth;
  const height = container.clientHeight;
  if (!width || !height) return;
  renderer.setSize(width, height);
  labels.setSize(width, height);
  camera.aspect = width / height;
  camera.updateProjectionMatrix();
}

function init() {
  const container = document.getElementById("model-view");
  renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true, preserveDrawingBuffer: true });
  renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
  container.append(renderer.domElement);
  labels = new CSS2DRenderer();
  labels.domElement.className = "model-labels";
  container.append(labels.domElement);
  scene = new THREE.Scene();
  scene.background = new THREE.Color(0xf4f6f8);
  scene.add(new THREE.AmbientLight(0xffffff, 1.5));
  const sun = new THREE.DirectionalLight(0xffffff, 1.6);
  sun.position.set(12, 30, 18);
  scene.add(sun);
  camera = new THREE.PerspectiveCamera(42, 1.5, 0.1, 500);
  controls = new OrbitControls(camera, renderer.domElement);
  controls.enableDamping = true;
  controls.maxPolarAngle = Math.PI * 0.62;
  controls.minDistance = 4;
  controls.maxDistance = 90;
  window.addEventListener("resize", resize);
  new ResizeObserver(resize).observe(container);
  resize();
  loop();
}

window.Model3D = {
  ready: true,
  load(sample) {
    if (!renderer) {
      try {
        init();
      } catch (error) {
        const fail = document.getElementById("model-fail");
        fail.textContent = "この端末では模型を出せません。下の表と連鎖の図で確かめてください。";
        fail.hidden = false;
        window.Model3D.failed = true;
        return;
      }
    }
    resize();
    clear();
    buildRooms(sample);
    buildEquipment(sample);
    buildElevator(sample);
    buildOutside(sample);
    buildUpper(sample);
    buildPins(sample);
    focusPoints.overview = { look: new THREE.Vector3(0, sample.archetype === "ground" ? 2 : -0.5, 0), from: new THREE.Vector3(15, sample.archetype === "ground" ? 8 : 6, 24) };
    camera.position.copy(focusPoints.overview.from);
    controls.target.copy(focusPoints.overview.look);
    this.sample = sample;
  },
  focus(key) {
    const point = focusPoints[key] || focusPoints.overview;
    if (!point) return false;
    targetCam = point.from.clone();
    targetLook = point.look.clone();
    focusKey = key;
    refreshDetails();
    return true;
  },
  // 水の面と止まる想定の色を、シナリオのとおりに変える。
  apply(state) {
    const { water, measure, scenario } = state;
    waters.forEach((item) => {
      item.target = waterTarget(item, water, measure, this.sample);
    });
    const stopped = new Set(scenario.stopped);
    setColor(meshes.hv, stopped.has("hv") ? COLORS.stopped : COLORS.panel);
    setColor(meshes.panel, stopped.has("panel") ? COLORS.stopped : COLORS.panel);
    setColor(meshes.pump_unit, stopped.has("pump") ? COLORS.stopped : COLORS.panel);
    setColor(meshes.ev, stopped.has("ev") ? COLORS.stopped : COLORS.key);
    setColor(meshes.tr, stopped.has("tr") ? COLORS.stopped : COLORS.trUnknown);
    if (meshes.panel) {
      const room = meshes.pump;
      const raised = measure === "raise";
      meshes.panel.position.y = room.position.y + (raised ? room.geometry.parameters.height / 2 - 0.65 : 0);
      raisedNow = raised;
      if (ghostPanel) ghostPanel.visible = raised;
      if (panelLabel) {
        // 札は盤と一緒に動かし、付け替えたときは付け替え後の文にする。
        // 付け替えた盤は部屋の札の高さに来るので、札を盤の横へずらして重ならないようにする。
        panelLabel.position.x = meshes.panel.position.x + (raised ? 1.6 : 0);
        panelLabel.position.y = meshes.panel.position.y + (raised ? -1.0 : 0.75);
        panelLabel.element.textContent = raised ? RAISED_PANEL_NOTE : `ポンプのスイッチ盤\n${panelHeightNote(this.sample)}`;
      }
      refreshDetails();
    }
    if (meshes.hole) setColor(meshes.hole, measure === "hole" ? 0x3a7d44 : 0xd9534f);
  },
  // 判定が変わったとき（書類・聞き取り・向き）に、模型を組み直さずに部屋の札の1行目だけ替える。
  updateTags() {
    if (!this.sample) return;
    Object.entries(roomTags).forEach(([key, head]) => fillRoomTag(head, key, this.sample));
  },
  // 2 タップで指定した向きを矢印で出す。模型の向きは説明用で、実際の方位ではない。
  setDirections(directions) {
    if (!group) return;
    if (directionGroup) {
      directionGroup.traverse((child) => {
        if (child.isCSS2DObject) child.element.remove();
      });
      group.remove(directionGroup);
    }
    directionGroup = new THREE.Group();
    const angles = { 北: 0, 北東: 45, 東: 90, 南東: 135, 南: 180, 南西: 225, 西: 270, 北西: 315 };
    [["water", 0xc8611f, "水が来そうな側"], ["door", 0x5b3f9e, "扉の側"]].forEach(([key, color, name]) => {
      const direction = directions[key];
      if (!direction) return;
      const radians = (angles[direction] * Math.PI) / 180;
      const unit = new THREE.Vector3(Math.sin(radians), 0, -Math.cos(radians));
      const edge = unit.clone().multiplyScalar(WIDTH * 0.7).add(new THREE.Vector3(0, 0.6, 0));
      const arrow = new THREE.ArrowHelper(unit.clone().negate(), edge, 4, color, 1.2, 0.8);
      directionGroup.add(arrow);
      const node = document.createElement("div");
      node.className = "model-label model-label-small";
      node.textContent = `${name}：${direction}（模型の向きは説明用）`;
      const tag = new CSS2DObject(node);
      tag.position.copy(edge).add(new THREE.Vector3(0, 0.8, 0));
      directionGroup.add(tag);
    });
    group.add(directionGroup);
  },
  // 動きの確認用。画面が裏にあって描画が止まっているときに、指定の回数だけ進める。
  advance(frames) {
    for (let i = 0; i < frames; i += 1) tick();
  },
  debug() {
    return { rooms: Object.keys(meshes), hidden: Object.keys(meshes).filter((key) => !meshes[key].visible), tags: Object.fromEntries(Object.entries(roomTags).map(([key, head]) => [key, head.textContent])), raised: raisedNow, waters: waters.map((w) => [w.key, Number(w.target.toFixed(2))]), camera: camera.position.toArray().map((v) => Number(v.toFixed(1))), focus: Object.keys(focusPoints) };
  },
};
window.dispatchEvent(new Event("model3d-ready"));
