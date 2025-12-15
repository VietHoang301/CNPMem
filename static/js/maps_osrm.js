// static/js/maps_osrm.js
// Mục tiêu: override renderRouteMap(stops, mapId) để vẽ đường thật bằng OSRM.
// stops: [{lat,lng,name,address,order}, ...]
// Yêu cầu: Leaflet đã được load (L exists)

(function () {
  const maps = {}; // cache map instances theo mapId

  function destroyMap(mapId) {
    if (maps[mapId]) {
      maps[mapId].remove();
      delete maps[mapId];
    }
  }

  async function callBackendOSRM(latlngs) {
    const res = await fetch("/api/osrm/route", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ coords: latlngs }),
    });
    const data = await res.json();
    if (!res.ok || !data.ok) {
      throw new Error(data.error || "OSRM failed");
    }
    return data; // {distance_m, duration_s, geometry}
  }

  function addMarkers(map, pts) {
    pts.forEach((p, idx) => {
      const ll = [p.lat, p.lng];
      const title = `${idx + 1}. ${p.name || "Trạm"}`;
      const addr = p.address || "";
      L.marker(ll).addTo(map).bindPopup(`<b>${title}</b><br>${addr}`);
    });
  }

  function fitBounds(map, latlngs) {
    if (!latlngs.length) return;
    map.fitBounds(latlngs, { padding: [20, 20] });
  }

  // fallback: vẽ đường thẳng nối các điểm
  function drawStraightLine(map, latlngs) {
    if (latlngs.length >= 2) {
      L.polyline(latlngs).addTo(map);
    }
  }

  // chuyển GeoJSON LineString (lng,lat) -> Leaflet latlng
  function geoJsonLineToLatLng(geometry) {
    if (!geometry || geometry.type !== "LineString" || !Array.isArray(geometry.coordinates)) return [];
    return geometry.coordinates.map(c => [c[1], c[0]]);
  }

  // cố gắng route 1 lần; nếu fail thì route theo từng cặp (chắc chắn chạy, nhưng nhiều request)
  async function drawRouteOSRM(map, latlngs) {
    if (latlngs.length < 2) return;

    try {
      const data = await callBackendOSRM(latlngs);
      const line = geoJsonLineToLatLng(data.geometry);
      if (line.length) L.polyline(line).addTo(map);
      return;
    } catch (e) {
      console.warn("OSRM full route failed, fallback pairwise:", e.message);
    }

    // fallback pairwise: route từng đoạn (i -> i+1)
    for (let i = 0; i < latlngs.length - 1; i++) {
      const seg = [latlngs[i], latlngs[i + 1]];
      try {
        const data = await callBackendOSRM(seg);
        const line = geoJsonLineToLatLng(data.geometry);
        if (line.length) L.polyline(line).addTo(map);
        else drawStraightLine(map, seg);
      } catch (e) {
        console.warn("OSRM segment failed, use straight:", e.message);
        drawStraightLine(map, seg);
      }
    }
  }

  // === HÀM CHÍNH: override renderRouteMap ===
  window.renderRouteMap = async function (stops, mapId) {
    if (!window.L) {
      console.error("Leaflet chưa được load: L is undefined");
      return;
    }
    if (!mapId) {
      console.error("Thiếu mapId");
      return;
    }

    const pts = (stops || [])
      .filter(s => s && s.lat != null && s.lng != null)
      .map(s => ({
        lat: Number(s.lat),
        lng: Number(s.lng),
        name: s.name || s.tenTram || "",
        address: s.address || s.diaChi || "",
        order: Number(s.order ?? s.thuTuTrenTuyen ?? 0),
      }))
      .filter(p => Number.isFinite(p.lat) && Number.isFinite(p.lng))
      .sort((a, b) => (a.order || 0) - (b.order || 0));

    if (pts.length === 0) return;

    destroyMap(mapId);

    const map = L.map(mapId);
    maps[mapId] = map;

    L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
      maxZoom: 19,
      attribution: "&copy; OpenStreetMap contributors",
    }).addTo(map);

    addMarkers(map, pts);

    const latlngs = pts.map(p => [p.lat, p.lng]);
    fitBounds(map, latlngs);

    // vẽ route thật
    if (latlngs.length >= 2) {
      await drawRouteOSRM(map, latlngs);
    }
  };
})();
