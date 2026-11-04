// 説明用の模型。箱だけをコードで作る。水は決めた段の高さへ動かすだけで、シミュレーションはしない。
import * as THREE from "three";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";
import { CSS2DObject, CSS2DRenderer } from "three/addons/renderers/CSS2DRenderer.js";

const WIDTH = 20;
const DEPTH = 16;
const FLOOR_H = 3.2;
const BASE_Y = -3.4;
// 部屋の色は平面図・断面図の塗り分けとそろえる（電気＝橙、水＝青、借室＝紫、そのほか＝灰。2026-11-04）。
const COLORS = {
  room: 0xdfe3e8,
  key: 0xbcd0e5,
  power: 0xf2b97a,
  waterRoom: 0x8fc2ea,
  tr: 0xb8a6dc,
  trUnknown: 0xa89bc4,
  stopped: 0xd9412b,
  water: 0x2f7fd0,
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
let hoverKey = null;
let leaderSvg = null;
let leaderMarkup = "";
let sizeMemo = new WeakMap();
let placeMemo = new WeakMap();
const candidateMemo = new Map();
const anchor = new THREE.Vector3();
const LAYOUT_GAP = 3;
const LAYOUT_EDGE = 2;
const LEADER_MIN = 6;
// この高さより狭い模型では、焦点でない部屋の札を名前の行までに畳む。
const ROOM_FULL_MIN_HEIGHT = 360;

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
  const object = new CSS2DObject(node);
  if (extra.head) {
    // 札の文は変えずに、名前の行と残りの行を分けて持つ。狭いときは残りの行から畳む（layoutLabels）。
    const [first, ...others] = text.split("\n");
    const name = document.createElement("span");
    name.textContent = `\n${first}`;
    node.append(extra.head, name);
    let rest = null;
    if (others.length) {
      rest = document.createElement("span");
      rest.textContent = `\n${others.join("\n")}`;
      node.append(rest);
    }
    object.userData.parts = { name, rest };
  } else if (detailOf && text.includes("\n")) {
    // 部屋を選んだときに出る補助の札も一行だけにし、残りの行（高さの値や「位置は図面で未確認」など）は指を置いたとき（title）に読む。
    const [first, ...rest] = text.split("\n");
    node.textContent = first;
    node.title = rest.join(" ");
  } else node.textContent = text;
  object.position.copy(position);
  object.userData.layout = { kind: detailOf ? "detail" : "misc", key: detailOf };
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

// 3D の札は短い部屋の名前だけにして、立体を隠さない（2026-11-04）。判定は札の文字にせず、名前の前の色の点で見せ、
// 判定の名前と確かめる人は、点に指を置いたとき（title）に読む。
function fillRoomTag(head, key, sample) {
  const { verdict, label: verdictLabel } = roomVerdict(key);
  const dot = document.createElement("span");
  dot.className = `model-dot tag-${verdict}`;
  const pin = (sample.pins || []).find((item) => item.target === key);
  const whoLabels = window.WHO_LABELS || {};
  const who = pin && whoLabels[pin.who_kind] ? `／確かめる：${whoLabels[pin.who_kind]}` : "";
  const unseen = (sample.confirmedRooms || []).includes(key) ? "" : "／位置は図面で未確認";
  head.title = `${verdictLabel}${unseen}${who}`;
  head.replaceChildren(dot);
}

// 3D の部屋の札に出す短い名前。
const SHORT_ROOM_NAMES = { elec: "電気室", tr: "変圧器室", pump: "ポンプ室", panel_room: "盤の部屋", tank: "貯留タンク", gen: "発電機室", park: "機械式駐車場", slope: "スロープ" };

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
  const mesh = box(Math.max(place.w - 0.2, 0.2), 1, Math.max(place.d - 0.2, 0.2), COLORS.water, 0.62);
  mesh.position.set(place.center.x, place.center.y - place.h / 2, place.center.z);
  mesh.scale.y = 0.001;
  group.add(mesh);
  waters.push({ key, mesh, baseY: place.center.y - place.h / 2, room: place, level: 0, target: 0 });
}

function roomKindColor(key) {
  if (key === "tr") return COLORS.tr;
  if (["elec", "panel_room", "gen"].includes(key)) return COLORS.power;
  if (["pump", "tank"].includes(key)) return COLORS.waterRoom;
  return COLORS.room;
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
      // 主な部屋（電気・水・借室）は色を濃く、そのほかの部屋と、地下のある建物の1階は薄くして、見る所をはっきりさせる。
      const ghostFloor = isGround && sample.archetype !== "ground";
      const opacity = closed ? 0.9 : main ? 0.62 : ghostFloor ? 0.06 : 0.16;
      const mesh = box(place.w - 0.1, place.h, place.d - 0.1, roomKindColor(room.key), opacity);
      mesh.position.copy(place.center);
      // 主な部屋は、図面で確かめるまで破線の箱にする。そのほかの部屋の線は薄くする。
      edges(mesh, main || closed ? 0x444444 : ghostFloor ? 0xd3d8de : 0xa7afb8, main && !sample.confirmedRooms.includes(room.key));
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
        const note = trUnseen ? "変圧器室？" : SHORT_ROOM_NAMES[room.key] || window.App.roomName(room.key);
        // 隣り合う部屋の札が重ならないよう、借室は少し上へずらす。
        const shift = { tr: [0, 1.2] }[room.key] || [0, 0.25];
        const head = document.createElement("span");
        head.className = "model-tag-line";
        fillRoomTag(head, room.key, sample);
        roomTags[room.key] = head;
        const tag = label(note, place.center.clone().add(new THREE.Vector3(shift[0], place.h / 2 + shift[1], 0)), "model-label model-room-name", null, { head });
        tag.userData.layout = { kind: "room", key: room.key };
      }
      if (room.key === "tr" && !["no", "unknown"].includes(sample.answers?.tr)) {
        const hidden = sample.confirmedRooms.includes("tr") ? "中は建物側から分からない" : "中は建物側から分からない\n位置は図面で未確認";
        label(hidden, place.center.clone(), "model-label model-label-small", "tr");
      }
      if (room.key === "park" || room.key === "slope") {
        label(SHORT_ROOM_NAMES[room.key], place.center.clone(), "model-label model-label-small", room.key);
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
  label("EVの底", pitPlace.center.clone().add(new THREE.Vector3(0, 1, 0)), "model-label model-label-small", "ev");
  // 昇降路の名前は短く「EV」とだけ、いつも出す。
  const name = label("EV", new THREE.Vector3(shaft.position.x, FLOOR_H * 2 + 0.3, shaft.position.z), "model-label model-room-name");
  name.userData.layout = { kind: "room", key: "ev" };
}

function buildOutside(sample) {
  const ground = box(WIDTH + 14, 0.1, DEPTH + 12, COLORS.ground, 0.14);
  ground.position.set(0, -0.05, 1);
  group.add(ground);
  // 地下のある建物は、奥と左に土の断面、下に床を描き、部屋が地面の下にあることを見て分かるようにする（2026-11-04）。
  if (sample.archetype !== "ground") {
    const depth = -BASE_Y + 0.6;
    const soil = 0xc9b48c;
    const back = box(WIDTH + 1.2, depth, 0.12, soil, 0.7);
    back.position.set(0, -depth / 2, -DEPTH / 2 - 0.3);
    const side = box(0.12, depth, DEPTH + 0.6, soil, 0.7);
    side.position.set(-WIDTH / 2 - 0.6, -depth / 2, 0);
    const slab = box(WIDTH + 1.2, 0.12, DEPTH + 0.6, 0x9aa0a6, 0.75);
    slab.position.set(0, BASE_Y - 0.06, 0);
    group.add(back, side, slab);
    label("地面の下", new THREE.Vector3(-WIDTH / 2 - 0.6, BASE_Y / 2, DEPTH / 2), "model-label model-label-small");
  }
  const road = box(WIDTH + 14, 0.08, 4, COLORS.road, 0.35);
  road.position.set(0, 0.02, DEPTH / 2 + 4.8);
  group.add(road);
  focusPoints.road = { look: road.position.clone(), from: road.position.clone().add(new THREE.Vector3(0, 6, 12)) };
  const roadWater = { center: new THREE.Vector3(0, 0.05, DEPTH / 2 + 4.8), w: WIDTH + 14, d: 4, h: 1 };
  addWater("road", roadWater);
  label("道路", road.position.clone().add(new THREE.Vector3(9, 0.5, 0)), "model-label model-label-small");

  if (sample.underground_feed) {
    const elec = meshes.elec;
    const cover = box(1.2, 0.12, 1.2, COLORS.conduit);
    const x = elec ? elec.position.x - 1.5 : -6;
    cover.position.set(x, 0.1, DEPTH / 2 + 2);
    group.add(cover);
    meshes.hh = cover;
    focusPoints.hh = { look: cover.position.clone(), from: cover.position.clone().add(new THREE.Vector3(3, 5, 7)) };
    label("東電の蓋（開けない）", cover.position.clone().add(new THREE.Vector3(0, 0.6, 0)), "model-label model-label-small", "hh");
    const startZ = elec ? elec.position.z + elec.geometry.parameters.depth / 2 : 0;
    const conduit = box(0.35, 0.35, DEPTH / 2 + 2 - startZ, COLORS.conduit);
    conduit.position.set(x, BASE_Y + 1.2, (startZ + DEPTH / 2 + 2) / 2);
    group.add(conduit);
    const riser = box(0.35, -BASE_Y - 1.2, 0.35, COLORS.conduit);
    riser.position.set(x, (BASE_Y + 1.2) / 2, DEPTH / 2 + 2);
    group.add(riser);
    label("電線の管", conduit.position.clone().add(new THREE.Vector3(-1.6, 0.4, 0)), "model-label model-label-small", "elec");
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
    label("扉・換気口", door.position.clone().add(new THREE.Vector3(0, 0.7, 0.3)), "model-label model-label-small");
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
    label("雨水ます", basin.position.clone().add(new THREE.Vector3(0, 0.6, 0)), "model-label model-label-small");
    const pipe = box(0.3, -BASE_Y, 0.3, COLORS.conduit);
    pipe.position.set(basin.position.x, BASE_Y / 2, basin.position.z);
    group.add(pipe);
  }
}

function buildUpper(sample) {
  // 上の階は3階分だけ薄く描く（高い建物でも、見たい地下と1階が小さくならないように）。
  const levels = Math.min(sample.floors - 1, 3);
  const height = levels * FLOOR_H;
  const footprintW = sample.archetype === "tower" ? WIDTH * 0.62 : WIDTH;
  const footprintD = sample.archetype === "tower" ? DEPTH * 0.62 : DEPTH;
  const mesh = box(footprintW, height, footprintD, COLORS.ghost, 0.04);
  mesh.position.set(0, FLOOR_H + height / 2, 0);
  edges(mesh, 0xc5ccd4);
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
    // ピンに指を乗せている間は、その部屋の札を畳まずに出す。
    const enter = () => { hoverKey = pin.focus; };
    const leave = () => { if (hoverKey === pin.focus) hoverKey = null; };
    node.addEventListener("pointerenter", enter);
    node.addEventListener("pointerleave", leave);
    node.addEventListener("focus", enter);
    node.addEventListener("blur", leave);
    const object = new CSS2DObject(node);
    object.userData.layout = { kind: "pin", key: pin.focus };
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
  hoverKey = null;
  sizeMemo = new WeakMap();
  placeMemo = new WeakMap();
  leaderMarkup = "";
  if (leaderSvg) leaderSvg.replaceChildren();
}

// 札の重なりをよける。CSS2DRenderer が置いた位置（transform）はそのままにし、
// 画面の上のずれだけを CSS の translate で足す。文は変えず、狭いときは行を畳むか、
// 名前のない補助の札（前の道路など）を一時的に隠す。動かした札には元の位置への細い線を引く。
function setLevel(object, level) {
  const parts = object.userData.parts;
  if (!parts) return;
  parts.name.hidden = level >= 2;
  if (parts.rest) parts.rest.hidden = level >= 1;
}

function labelSize(object, level) {
  const el = object.element;
  let memo = sizeMemo.get(el);
  if (!memo) {
    memo = new Map();
    sizeMemo.set(el, memo);
  }
  const key = `${level}|${el.textContent}`;
  let size = memo.get(key);
  if (!size) {
    setLevel(object, level);
    size = [el.offsetWidth, el.offsetHeight];
    if (size[0] && size[1]) memo.set(key, size);
  }
  return size;
}

// 札を置いてみる候補のずれ。縦に少しずつ、横は札の幅の割合で動かし、近い順に並べる。
function candidates(w, h, H) {
  const key = `${w}|${h}|${H}`;
  let list = candidateMemo.get(key);
  if (list) return list;
  list = [];
  const xs = [0, 0.3, -0.3, 0.6, -0.6, 1, -1].map((f) => Math.round(f * (w + LAYOUT_GAP)));
  for (let dy = -H; dy <= H; dy += 6) xs.forEach((dx) => list.push([dx, dy, Math.abs(dy) + Math.abs(dx) * 0.5]));
  list.sort((a, b) => a[2] - b[2]);
  if (candidateMemo.size > 400) candidateMemo.clear();
  candidateMemo.set(key, list);
  return list;
}

function layoutRank(object) {
  const info = object.userData.layout || { kind: "misc" };
  if (info.kind === "pin") return 0;
  if (info.kind === "room") return info.key === focusKey || info.key === hoverKey ? 1 : 3;
  if (info.kind === "detail") return 2;
  return 4;
}

function overlapArea(rect, placed) {
  let area = 0;
  placed.forEach((other) => {
    const w = Math.min(rect[2], other[2]) - Math.max(rect[0], other[0]);
    const h = Math.min(rect[3], other[3]) - Math.max(rect[1], other[1]);
    if (w > 0 && h > 0) area += w * h;
  });
  return area;
}

function layoutLabels() {
  if (!group || !labels) return;
  const { width: W, height: H } = labels.getSize();
  if (!W || !H) return;
  const items = [];
  group.traverse((object) => {
    if (!object.isCSS2DObject || object.element.style.display === "none") return;
    anchor.setFromMatrixPosition(object.matrixWorld).project(camera);
    items.push({ object, x: ((anchor.x + 1) / 2) * W, y: ((1 - anchor.y) / 2) * H, rank: layoutRank(object), order: items.length });
  });
  items.sort((a, b) => a.rank - b.rank || a.y - b.y || a.order - b.order);
  const placed = [];
  const leaders = [];
  items.forEach((item) => {
    const { object, x, y, rank } = item;
    const el = object.element;
    const info = object.userData.layout || { kind: "misc" };
    // 元の位置が模型の外に出た札は出さない（端で切れて重なるだけなので）。
    if (x < 0 || x > W || y < 0 || y > H) {
      el.style.visibility = "hidden";
      return;
    }
    const isRoom = info.kind === "room";
    const firstLevel = isRoom && rank !== 1 && H < ROOM_FULL_MIN_HEIGHT ? 1 : 0;
    // 部屋の札は短い名前だけなので、名前は畳まない（置けないときは札ごと隠す）。
    const lastLevel = isRoom ? 1 : 0;
    const memo = placeMemo.get(el);
    let chosen = null;
    let best = null;
    for (let level = firstLevel; level <= lastLevel && !chosen; level += 1) {
      const [w, h] = labelSize(object, level);
      if (!w || !h) continue;
      const tryOffset = (dx, dy) => {
        const left = Math.max(LAYOUT_EDGE, Math.min(x - w / 2 + dx, W - w - LAYOUT_EDGE));
        const top = Math.max(LAYOUT_EDGE, Math.min(y - h / 2 + dy, H - h - LAYOUT_EDGE));
        const rect = [left, top, left + w, top + h];
        const padded = [left - LAYOUT_GAP, top - LAYOUT_GAP, left + w + LAYOUT_GAP, top + h + LAYOUT_GAP];
        const area = overlapArea(padded, placed);
        const result = { level, rect, dx: left - (x - w / 2), dy: top - (y - h / 2) };
        if (area === 0) return result;
        if (level === lastLevel && (!best || area < best.area)) best = { ...result, area };
        return null;
      };
      if (memo && memo.level === level) chosen = tryOffset(memo.dx, memo.dy);
      if (!chosen) {
        const list = candidates(w, h, H);
        for (let i = 0; i < list.length && !chosen; i += 1) chosen = tryOffset(list[i][0], list[i][1]);
      }
    }
    // 置き場がないとき：ピン・焦点の札・焦点の部屋の補助の札は一番重ならない所に置く。
    // それ以外は隠す（部屋の札は、ピンの印と平面図で同じ場所を示せる）。
    if (!chosen && rank <= 2 && best) chosen = best;
    if (!chosen) {
      el.style.visibility = "hidden";
      el.style.translate = "";
      placeMemo.delete(el);
      return;
    }
    setLevel(object, chosen.level);
    el.style.visibility = "";
    const dx = Math.round(chosen.dx);
    const dy = Math.round(chosen.dy);
    el.style.translate = dx || dy ? `${dx}px ${dy}px` : "";
    placeMemo.set(el, { level: chosen.level, dx: chosen.dx, dy: chosen.dy });
    placed.push(chosen.rect);
    if (Math.hypot(dx, dy) > LEADER_MIN) {
      const [l, t, r, b] = chosen.rect;
      const px = Math.max(l, Math.min(x, r));
      const py = Math.max(t, Math.min(y, b));
      if (Math.hypot(px - x, py - y) > 2) leaders.push(`<line x1="${x.toFixed(1)}" y1="${y.toFixed(1)}" x2="${px.toFixed(1)}" y2="${py.toFixed(1)}"/><circle cx="${x.toFixed(1)}" cy="${y.toFixed(1)}" r="2"/>`);
    }
  });
  const markup = leaders.join("");
  if (leaderSvg && markup !== leaderMarkup) {
    leaderMarkup = markup;
    leaderSvg.innerHTML = markup;
  }
}

// 盤・受電の箱の部屋に水が入るか。サーバーの scenario（水の位置③の wet に hv があるか）のとおりにし、ここで計算し直さない。
function powerRoomReached(measure) {
  const wet = window.App?.building?.scenarios?.[`3:${measure}`]?.wet;
  return wet ? wet.includes("hv") : measure !== "hole";
}

function waterTarget(item, level, measure, sample) {
  if (level <= 0) return 0;
  if (item.key === "road") return level >= 3 ? 0.6 : level >= 1 ? 0.3 : 0;
  if (item.key === "ev") return level >= 2 ? 0.8 : 0;
  if (item.key === "tr" && level < 3) return 0;
  if ((item.key === "elec" || item.key === "panel_room") && !powerRoomReached(measure)) return 0;
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
  layoutLabels();
}

function resize() {
  const container = document.getElementById("model-view");
  const width = container.clientWidth;
  const height = container.clientHeight;
  if (!width || !height) return;
  renderer.setSize(width, height);
  labels.setSize(width, height);
  if (leaderSvg) leaderSvg.setAttribute("viewBox", `0 0 ${width} ${height}`);
  camera.aspect = width / height;
  camera.updateProjectionMatrix();
}

function init() {
  const container = document.getElementById("model-view");
  renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true, preserveDrawingBuffer: true });
  renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
  container.append(renderer.domElement);
  // 動かした札と元の位置を結ぶ線。札の下、模型の上に重ねる。
  leaderSvg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  leaderSvg.setAttribute("class", "model-leaders");
  leaderSvg.setAttribute("aria-hidden", "true");
  leaderSvg.style.cssText = "position:absolute;inset:0;width:100%;height:100%;pointer-events:none;overflow:visible;stroke:#5b5f66;stroke-width:1;fill:#5b5f66;";
  container.append(leaderSvg);
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
    // 最初の向きは、地下と1階が大きく見える近さにする。
    focusPoints.overview = { look: new THREE.Vector3(0, sample.archetype === "ground" ? 1.2 : -1.4, 0), from: new THREE.Vector3(12, sample.archetype === "ground" ? 7 : 5, 19) };
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
        // 一行目だけを札に出し、残りは指を置いたとき（title）に読む（ほかの補助の札と同じ）。
        const [first, ...rest] = (raised ? RAISED_PANEL_NOTE : `ポンプのスイッチ盤\n${panelHeightNote(this.sample)}`).split("\n");
        panelLabel.element.textContent = first;
        panelLabel.element.title = rest.join(" ");
      }
      refreshDetails();
    }
    if (meshes.hole) setColor(meshes.hole, measure === "hole" ? 0x3a7d44 : 0xd9534f);
    this.measure = measure;
  },
  // 時間の再生（web/section-anim.js）から、水の位置を続いた値 flow（0〜3）で渡す。
  // 段の間は前後の段の高さを混ぜるだけで、水の量や速さは計算しない。止まる色は apply の scenario のまま。
  // 外の水（道路）と中の水（部屋）を別々に動かせる。inside を省くと同じ値（前の版の呼び方）。
  setFlow(flow, inside) {
    if (!this.sample || flow === null || flow === undefined) return;
    const measure = this.measure || "plate";
    const at = (value, item) => {
      const low = Math.floor(value);
      const high = Math.min(3, Math.ceil(value));
      const from = waterTarget(item, low, measure, this.sample);
      const to = waterTarget(item, high, measure, this.sample);
      return from + (to - from) * (value - low);
    };
    waters.forEach((item) => {
      item.target = at(item.key === "road" || inside === undefined ? flow : inside, item);
    });
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
