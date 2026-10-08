"""
地理编码（免 Key）：
  · 城市中心：Open-Meteo 地理编码
  · 具体地点：Photon（基于 OpenStreetMap）
OSM 坐标是 WGS-84，高德地图用 GCJ-02（国内偏移约 300-600 米），这里统一转成 GCJ-02 再交给前端。
"""

from __future__ import annotations

import logging
import math
import threading

import requests

logger = logging.getLogger(__name__)

_UA = {"User-Agent": "yipaijihe/1.0 (travel planner)"}
_CITY_CACHE: dict[str, tuple[float, float] | None] = {}
_POI_CACHE: dict[tuple[str, str], tuple[float, float] | None] = {}
_LOCK = threading.Lock()


# ------------------------------------------------------------ 坐标系转换 ----
_A = 6378245.0
_EE = 0.00669342162296594323


def _out_of_china(lat: float, lng: float) -> bool:
    return not (73.66 < lng < 135.05 and 3.86 < lat < 53.55)


def _t_lat(x: float, y: float) -> float:
    r = -100.0 + 2.0 * x + 3.0 * y + 0.2 * y * y + 0.1 * x * y + 0.2 * math.sqrt(abs(x))
    r += (20.0 * math.sin(6.0 * x * math.pi) + 20.0 * math.sin(2.0 * x * math.pi)) * 2.0 / 3.0
    r += (20.0 * math.sin(y * math.pi) + 40.0 * math.sin(y / 3.0 * math.pi)) * 2.0 / 3.0
    r += (160.0 * math.sin(y / 12.0 * math.pi) + 320 * math.sin(y * math.pi / 30.0)) * 2.0 / 3.0
    return r


def _t_lng(x: float, y: float) -> float:
    r = 300.0 + x + 2.0 * y + 0.1 * x * x + 0.1 * x * y + 0.1 * math.sqrt(abs(x))
    r += (20.0 * math.sin(6.0 * x * math.pi) + 20.0 * math.sin(2.0 * x * math.pi)) * 2.0 / 3.0
    r += (20.0 * math.sin(x * math.pi) + 40.0 * math.sin(x / 3.0 * math.pi)) * 2.0 / 3.0
    r += (150.0 * math.sin(x / 12.0 * math.pi) + 300.0 * math.sin(x / 30.0 * math.pi)) * 2.0 / 3.0
    return r


def wgs84_to_gcj02(lat: float, lng: float) -> tuple[float, float]:
    if _out_of_china(lat, lng):
        return lat, lng
    d_lat = _t_lat(lng - 105.0, lat - 35.0)
    d_lng = _t_lng(lng - 105.0, lat - 35.0)
    rad = lat / 180.0 * math.pi
    magic = 1 - _EE * math.sin(rad) ** 2
    sq = math.sqrt(magic)
    d_lat = (d_lat * 180.0) / ((_A * (1 - _EE)) / (magic * sq) * math.pi)
    d_lng = (d_lng * 180.0) / (_A / sq * math.cos(rad) * math.pi)
    return round(lat + d_lat, 6), round(lng + d_lng, 6)


def km_between(a: tuple[float, float], b: tuple[float, float]) -> float:
    lat1, lng1, lat2, lng2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    h = math.sin((lat2 - lat1) / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin((lng2 - lng1) / 2) ** 2
    return 6371 * 2 * math.asin(math.sqrt(h))


# ------------------------------------------------------------ 城市 / 地点 ----
def city_center(city: str) -> tuple[float, float] | None:
    """城市中心（WGS-84），失败返回 None；结果（含失败）会缓存"""
    city = (city or "").strip()
    if not city:
        return None
    with _LOCK:
        if city in _CITY_CACHE:
            return _CITY_CACHE[city]
    coords = None
    try:
        resp = requests.get(
            "https://geocoding-api.open-meteo.com/v1/search",
            params={"name": city, "count": 1, "language": "zh", "format": "json"},
            timeout=6,
        )
        resp.raise_for_status()
        hit = (resp.json().get("results") or [None])[0]
        coords = (hit["latitude"], hit["longitude"]) if hit else None
    except Exception as e:  # noqa: BLE001 — 网络问题不缓存，下次再试
        logger.warning("城市地理编码失败（%s）: %s", city, e)
        return None
    with _LOCK:
        _CITY_CACHE[city] = coords
    return coords


def locate(name: str, city: str, near: tuple[float, float] | None = None, radius_km: float = 80) -> tuple[float, float] | None:
    """地点名 → GCJ-02 坐标。只接受离城市中心 radius_km 以内的结果，避免同名地点跑到外地。"""
    key = (name, city)
    with _LOCK:
        if key in _POI_CACHE:
            return _POI_CACHE[key]
    near = near or city_center(city)
    params = {"q": f"{name} {city}", "limit": 5}
    if near:
        params.update(lat=near[0], lon=near[1])
    try:
        resp = requests.get("https://photon.komoot.io/api/", params=params, headers=_UA, timeout=6)
        resp.raise_for_status()
        features = resp.json().get("features") or []
    except Exception as e:  # noqa: BLE001
        logger.info("地点地理编码失败（%s）: %s", name, e)
        return None
    found = None
    for f in features:
        lng, lat = f["geometry"]["coordinates"][:2]
        if near and km_between(near, (lat, lng)) > radius_km:
            continue
        found = wgs84_to_gcj02(lat, lng)
        break
    with _LOCK:
        _POI_CACHE[key] = found
    return found


def fill_missing(places: list[dict], city: str) -> list[dict]:
    """给缺坐标的地点补坐标（并行查询）。查不到的保持为空，前端会再用高德搜索定位。"""
    from concurrent.futures import ThreadPoolExecutor

    todo = [p for p in places if p.get("lat") in (None, "") or p.get("lng") in (None, "")]
    if not todo:
        return places
    near = city_center(city)
    with ThreadPoolExecutor(max_workers=6) as pool:
        for p, hit in zip(todo, pool.map(lambda x: locate(x["name"], city, near), todo)):
            if hit:
                p["lat"], p["lng"] = hit
    return places
