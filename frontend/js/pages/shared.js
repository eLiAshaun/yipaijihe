import { h, mountInto } from "../core/dom.js";
import { icon, typeIcon, typeLabel } from "../core/icons.js";
import { api } from "../core/api.js";
import { state, bus, persistDraft } from "../core/state.js";
import { dayColorVar, dayHex } from "../core/config.js";
import { createMapView } from "../services/map.js";
import { daySegments, dayStats, dayDate, fmtDate, fmtDuration, hasCoords, stopLocation, stopName, TRAVEL_MODES, estimateCost } from "../services/planner.js";
import { normalizeItinerary } from "../services/itinerary.js";
import { toast } from "../ui/toast.js";

/** 只读分享页：任何人凭链接可看，无需登录 */
export default {
  title: () => "分享的行程",

  mount(root, ctx) {
    const page = h("section", { class: "page page--wide shared" });
    root.append(page);
    mountInto(page, h("div", { class: "skeleton", style: { height: "320px" } }));

    api.get(`/api/trips/shared/${encodeURIComponent(ctx.params.token)}`, { signal: ctx.signal }).then(async ({ trip }) => {
      if (!ctx.alive()) return;
      const itin = normalizeItinerary(trip.itinerary);
      const cost = estimateCost(itin, { budget: trip.budget });
      const mapEl = h("div", { class: "map-canvas" });

      const copy = () => {
        if (!state.user) {
          sessionStorage.setItem("ypjh_pending_share", ctx.params.token);
          toast("登录后即可复制为自己的行程");
          return ctx.navigate("login");
        }
        state.itinerary = itin;
        state.tripId = null;
        state.trip = { city: trip.city, days: itin.days.length, budget: trip.budget || 0, startDate: trip.start_date || "", pace: trip.meta?.pace || "" };
        state.feedbacks = {};
        state.cost = cost;
        persistDraft();
        bus.emit("itinerary:ready");
        toast("已复制到你的行程，可以随意修改");
        ctx.navigate("itinerary");
      };

      mountInto(
        page,
        h("div", { class: "page-head" },
          h("p", { class: "eyebrow" }, `${trip.author} 分享的行程`),
          h("h1", null, trip.title || `${trip.city}${trip.days}日游`),
          h("p", null, itin.summary),
          h("div", { class: "chip-row" }, h("span", { class: "chip" }, icon("calendar"), `${itin.days.length} 天`), h("span", { class: "chip" }, icon("pin"), `${trip.stops} 个地点`), h("span", { class: "chip" }, icon("wallet"), `人均约 ¥${cost.per_person}`), trip.mbti_type && h("span", { class: "chip mono" }, trip.mbti_type)),
          h("div", { class: "video-actions" }, h("button", { class: "btn btn--primary", type: "button", onclick: copy }, icon("copy"), state.user ? "复制为我的行程" : "登录并复制为我的行程"), h("a", { class: "btn btn--ghost", href: state.user ? "#/plan" : "#/login" }, "自己规划一个"))),
        h("div", { class: "split" },
          h("div", { class: "shared-days" }, itin.days.map((day, di) => {
            const st = dayStats(day);
            const dt = dayDate(trip.start_date, di);
            return h("section", { class: "day", style: { "--dc": dayColorVar(di) } },
              h("header", { class: "day-head" }, h("span", { class: "day-badge mono" }, `D${di + 1}`), h("div", { class: "day-title" }, h("h3", null, day.title), h("small", { class: "faint" }, dt ? fmtDate(dt) : "")), h("span", { class: "faint mono", style: { fontSize: "var(--fs-xs)" } }, `${st.count} 个点 · 通勤 ${fmtDuration(st.travelMin)}`)),
              h("ol", { class: "ro-stops" }, daySegments(day).flatMap((seg) => [
                seg.travel && h("li", { class: "ro-travel" }, icon(TRAVEL_MODES[seg.travel.mode].icon), `${TRAVEL_MODES[seg.travel.mode].label} ${seg.travel.minutes} 分钟`),
                h("li", { class: "ro-stop" }, h("span", { class: "mono ro-time", style: { color: dayColorVar(di) } }, seg.stop.time || ""), h("div", null, h("b", null, stopName(seg.stop)), stopLocation(seg.stop).type && h("span", { class: "type-badge", "data-type": stopLocation(seg.stop).type, style: { marginLeft: "8px" } }, icon(typeIcon(stopLocation(seg.stop).type)), typeLabel(stopLocation(seg.stop).type)), seg.stop.notes && h("p", { class: "muted", style: { fontSize: "var(--fs-sm)" } }, seg.stop.notes)))
              ])));
          })),
          h("div", { class: "sticky" }, h("div", { class: "map-frame" }, mapEl)))
      );

      const map = await createMapView(mapEl, {});
      if (!ctx.alive()) return map.destroy();
      ctx.disposer.add(() => map.destroy());
      const markers = [];
      const segs = [];
      itin.days.forEach((d, di) => {
        const pts = d.items.filter((s) => hasCoords(stopLocation(s)));
        pts.forEach((s, si) => markers.push({ id: s.__stopId, lng: +stopLocation(s).lng, lat: +stopLocation(s).lat, label: String(d.items.indexOf(s) + 1), color: dayHex(di), title: stopName(s) }));
        for (let i = 0; i < pts.length - 1; i++) segs.push({ from: { lng: +stopLocation(pts[i]).lng, lat: +stopLocation(pts[i]).lat }, to: { lng: +stopLocation(pts[i + 1]).lng, lat: +stopLocation(pts[i + 1]).lat }, color: dayHex(di) });
      });
      map.setMarkers(markers);
      map.fit();
      map.setRoutes(segs, "transfer", { city: trip.city });
    }).catch((e) => {
      if (!ctx.alive() || e.name === "AbortError") return;
      mountInto(page, h("div", { class: "empty" }, h("h3", null, "这个分享链接打不开"), h("p", null, e.message), h("a", { class: "btn btn--ink", href: state.user ? "#/plan" : "#/login" }, "去规划自己的行程")));
    });
  },
};
