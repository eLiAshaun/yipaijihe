import test from "node:test";
import assert from "node:assert/strict";
import {
  toMin, fromMin, haversine, estimateTravel, dayStats, dayWarnings, reflowDay, optimizeDay,
  estimateCost, buildIcs, buildPackingList, buddyCompatibility, paceFromPersona, weatherInfo, toShareText,
} from "../../frontend/js/services/planner.js";

const P = (name, lat, lng, type = "landmark", extra = {}) => ({
  time: "09:00", activity: name, __stopId: name,
  location: { name, lat, lng, type, duration_min: 60, cost_level: "中等", ...extra },
});
// 外滩 / 豫园 / 武康路 / 田子坊 —— 真实坐标
const BUND = P("外滩", 31.2400, 121.4900);
const YUYUAN = P("豫园", 31.2270, 121.4920);
const WUKANG = P("武康路", 31.2070, 121.4380);
const TIANZIFANG = P("田子坊", 31.2090, 121.4680);

test("time helpers round-trip", () => {
  assert.equal(toMin("09:30"), 570);
  assert.equal(fromMin(570), "09:30");
  assert.equal(toMin("bad"), null);
  assert.equal(fromMin(99999), "23:59");
});

test("haversine ≈ known distance (外滩→豫园 ≈ 1.5km)", () => {
  const d = haversine(BUND.location, YUYUAN.location);
  assert.ok(d > 1300 && d < 1700, String(d));
});

test("estimateTravel picks mode by distance", () => {
  assert.equal(estimateTravel(BUND.location, YUYUAN.location).mode, "transit");
  const near = { lat: 31.24, lng: 121.491 };
  assert.equal(estimateTravel(BUND.location, near).mode, "walk");
  assert.equal(estimateTravel({ lat: 31.24, lng: 121.49 }, { lat: 31.05, lng: 121.8 }).mode, "taxi");
  assert.equal(estimateTravel({}, BUND.location), null);
});

test("reflowDay lays out sequential times incl. travel, snapped to 15min", () => {
  const day = reflowDay({ items: [BUND, YUYUAN, TIANZIFANG] }, { startTime: "09:00" });
  const t = day.items.map((s) => toMin(s.time));
  assert.equal(t[0], 540);
  assert.ok(t[1] >= 540 + 60 + 3 && t[1] % 15 === 0);
  assert.ok(t[2] > t[1] + 60);
});

test("reflowDay pushes a restaurant into the lunch window", () => {
  const lunch = P("小杨生煎", 31.23, 121.47, "food");
  const day = reflowDay({ items: [BUND, lunch] }, { startTime: "09:00" });
  assert.ok(toMin(day.items[1].time) >= 11 * 60 + 30);
});

test("dayWarnings: time conflict, overload, too-late, no-meal", () => {
  const a = { ...BUND, time: "09:00" };
  const b = { ...WUKANG, time: "10:00" }; // 外滩结束 10:00，武康路 ~5km 需要通勤
  const conflict = dayWarnings({ items: [a, b] }).find((w) => w.code === "time-conflict");
  assert.ok(conflict);

  const many = Array.from({ length: 6 }, (_, i) => ({ ...BUND, __stopId: "s" + i, time: fromMin(9 * 60 + i * 90) }));
  assert.ok(dayWarnings({ items: many }, "balanced").some((w) => w.code === "overload"));
  assert.ok(!dayWarnings({ items: many }, "packed").some((w) => w.code === "overload"));

  const late = { ...BUND, time: "22:00" };
  assert.ok(dayWarnings({ items: [late] }).some((w) => w.code === "too-late"));
  assert.ok(dayWarnings({ items: many }).some((w) => w.code === "no-meal"));
});

test("optimizeDay finds a shorter order and keeps the first stop", () => {
  // 故意乱序：外滩 → 武康路 → 豫园 → 田子坊
  const day = { items: [BUND, WUKANG, YUYUAN, TIANZIFANG] };
  const { day: better, savedMeters } = optimizeDay(day);
  assert.ok(savedMeters > 0);
  assert.equal(better.items[0].__stopId, "外滩");
  assert.equal(better.items.length, 4);
  const names = better.items.map((s) => s.__stopId);
  assert.deepEqual([...names].sort(), ["外滩", "武康路", "田子坊", "豫园"].sort());
  assert.equal(names[1], "豫园"); // 外滩→豫园→田子坊→武康路 是最短
});

test("optimizeDay is a no-op when already optimal / too few stops", () => {
  const { savedMeters } = optimizeDay({ items: [BUND, YUYUAN] });
  assert.equal(savedMeters, 0);
});

test("estimateCost sums per-person cost and compares with budget", () => {
  const it = { days: [{ items: [BUND, P("面馆", 31.24, 121.5, "food", { cost_level: "低" })] }] };
  const c = estimateCost(it, { budget: 100 });
  assert.equal(c.spots, 50); // 非餐饮「中等」= 50
  assert.equal(c.food, 35); // 餐饮「低」= 35
  assert.ok(c.per_person >= 85);
  assert.equal(c.within_budget, true);
  assert.equal(estimateCost(it, { budget: 50 }).within_budget, false);
  assert.ok(c.diff >= 0);
});

test("weatherInfo maps WMO codes", () => {
  assert.equal(weatherInfo(0).label, "晴");
  assert.equal(weatherInfo(63).rain, true);
  assert.equal(weatherInfo(95).icon, "storm");
});

test("packing list reacts to weather + persona", () => {
  const list = buildPackingList({
    days: 4,
    weather: [{ code: 63, tmax: 34, tmin: 4, rain_prob: 80 }],
    persona: { dimensions: [{ value: "D" }], mbti: "DRPT" },
    hasBuddy: true,
  });
  const text = JSON.stringify(list);
  for (const w of ["折叠伞", "防晒", "保暖外套", "相机", "换洗衣物", "搭子", "预约"]) assert.ok(text.includes(w), w);
});

test("ICS output is valid-looking, escaped and dated", () => {
  const it = { days: [{ title: "Day1", items: [{ ...BUND, time: "09:30", notes: "看夜景,拍照;记得带伞" }] }] };
  const ics = buildIcs(it, { startDate: "2026-10-01", city: "上海" });
  assert.ok(ics.startsWith("BEGIN:VCALENDAR\r\n"));
  assert.ok(ics.includes("DTSTART;TZID=Asia/Shanghai:20261001T093000"));
  assert.ok(ics.includes("DTEND;TZID=Asia/Shanghai:20261001T103000"));
  assert.ok(ics.includes(String.raw`看夜景\,拍照\;记得带伞`));
  assert.ok(ics.trim().endsWith("END:VCALENDAR"));
  for (const line of ics.split("\r\n")) assert.ok(new TextEncoder().encode(line).length <= 76, line);
});

test("ICS without a start date emits no events", () => {
  const ics = buildIcs({ days: [{ items: [BUND] }] }, {});
  assert.ok(!ics.includes("BEGIN:VEVENT"));
});

test("share text is readable", () => {
  const txt = toShareText({ summary: "好玩", days: [{ title: "Day 1", items: [{ ...BUND, time: "09:00" }] }], tips: ["带伞"] }, { city: "上海", startDate: "2026-10-01" });
  assert.match(txt, /上海1日行程/);
  assert.match(txt, /10月1日 周四/);
  assert.match(txt, /09:00 {2}外滩/);
});

test("buddy compatibility & pace inference", () => {
  const c = buddyCompatibility("DRPT", "ILSC");
  assert.equal(c.score, 0);
  assert.equal(c.tips.length, 4);
  assert.equal(buddyCompatibility("DRPT", "DRPT").score, 100);
  assert.equal(paceFromPersona({ mbti: "DRPC" }), "packed");
  assert.equal(paceFromPersona({ mbti: "DRPT" }), "relaxed");
  assert.equal(dayStats({ items: [] }).count, 0);
});
