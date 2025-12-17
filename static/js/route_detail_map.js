// static/js/route_detail_map.js
// Trang chi tiết tuyến: vẽ map + danh sách trạm theo từng hướng với chống race condition.

document.addEventListener("DOMContentLoaded", () => {
  const page = document.getElementById("routeDetailPage");
  if (!page) return;

  const routeId = page.dataset.routeId;
  const mapId = "route-map";

  const btnDi = document.getElementById("btnDi");
  const btnVe = document.getElementById("btnVe");
  const stopsTitle = document.getElementById("stopsTitle");
  const stopCountBadge = document.getElementById("stopCountBadge");
  const stopsList = document.getElementById("stopsList");
  const stopsEmpty = document.getElementById("stopsEmpty");
  const directionStatus = document.getElementById("directionStatus");
  const mapLoading = document.getElementById("mapLoading");

  const kpiStops = document.getElementById("kpiStops");
  const kpiStopsGeo = document.getElementById("kpiStopsGeo");
  const kpiDataStatus = document.getElementById("kpiDataStatus");

  let currentDir = "DI";
  let requestSeq = 0;

  function setActiveDir(dir) {
    const isDi = dir === "DI";
    btnDi.className = "btn btn-sm " + (isDi ? "btn-dark" : "btn-outline-dark");
    btnVe.className = "btn btn-sm " + (!isDi ? "btn-dark" : "btn-outline-dark");
    stopsTitle.textContent = `Danh sách trạm (${isDi ? "Lượt đi" : "Lượt về"})`;
  }

  function showStatus(msg, variant = "info") {
    if (!directionStatus) return;
    if (!msg) {
      directionStatus.classList.add("d-none");
      directionStatus.textContent = "";
      return;
    }
    directionStatus.textContent = msg;
    directionStatus.className = `alert alert-${variant} py-2 px-3 mt-2`;
  }

  function resetList() {
    stopsList.innerHTML = "";
    stopsList.classList.add("d-none");
    stopsEmpty.classList.remove("d-none");
    stopCountBadge.textContent = "0";
    kpiStops.textContent = "0";
    kpiStopsGeo.textContent = "0";
    kpiDataStatus.textContent = "—";
  }

  function setLoading(isLoading) {
    if (!mapLoading) return;
    mapLoading.classList.toggle("d-none", !isLoading);
  }

  function renderStops(stops) {
    if (!stops || !stops.length) {
      resetList();
      return;
    }

    stopsList.classList.remove("d-none");
    stopsEmpty.classList.add("d-none");
    stopsList.innerHTML = "";

    stops.forEach((s, idx) => {
      const li = document.createElement("li");
      li.className = "sb-stop-item";
      const safeName = s.name || s.stop_name || "";
      const safeAddr = s.address || s.diaChi || "";
      const lat = s.lat != null ? Number(s.lat) : null;
      const lng = s.lng != null ? Number(s.lng) : null;
      li.dataset.lat = lat;
      li.dataset.lng = lng;
      li.innerHTML = `
        <div class="fw-semibold">${s.order ?? idx + 1}. ${safeName}</div>
        ${safeAddr ? `<div class="text-muted small">${safeAddr}</div>` : ""}
      `;
      if (Number.isFinite(lat) && Number.isFinite(lng) && typeof window.focusStopOnMap === "function") {
        li.style.cursor = "pointer";
        li.addEventListener("click", () => {
          window.focusStopOnMap(mapId, lat, lng, 16);
        });
      }
      stopsList.appendChild(li);
    });
  }

  function updateKpis(stops) {
    const total = stops.length;
    const withGeo = stops.filter((s) => s.lat != null && s.lng != null).length;
    const ok = total >= 2 && withGeo >= 2;

    stopCountBadge.textContent = String(total);
    kpiStops.textContent = String(total);
    kpiStopsGeo.textContent = String(withGeo);
    kpiDataStatus.textContent = ok ? "Đủ" : "Thiếu";
  }

  async function loadStops(dir) {
    currentDir = dir;
    requestSeq += 1;
    const seq = requestSeq;

    setActiveDir(dir);
    showStatus("Đang tải dữ liệu trạm…", "info");
    setLoading(true);
    resetList();
    if (typeof window.renderRouteMap === "function") await window.renderRouteMap([], mapId);

    try {
      const res = await fetch(`/api/routes/${routeId}/stops_geo?dir=${dir}`);
      const data = await res.json();

      if (seq !== requestSeq) return; // có yêu cầu mới hơn

      if (!res.ok || !Array.isArray(data)) {
        showStatus("Không tải được trạm. Kiểm tra dữ liệu tuyến hoặc API.", "warning");
        await window.renderRouteMap([], mapId);
        setLoading(false);
        return;
      }

      const stops = data
        .slice()
        .sort((a, b) => Number(a.order ?? 0) - Number(b.order ?? 0));

      renderStops(stops);
      updateKpis(stops);

      if (typeof window.renderRouteMap === "function") await window.renderRouteMap(stops, mapId);

      if (!stops.length) {
        showStatus("Lượt này chưa có trạm hoặc đang trống dữ liệu.", "secondary");
      } else {
        showStatus("Đã tải xong. Tuyến được vẽ theo OSRM với fallback pairwise khi cần.", "success");
      }
      setLoading(false);
    } catch (err) {
      if (seq !== requestSeq) return;
      console.error(err);
      showStatus("Lỗi tải dữ liệu trạm. Map đã được reset để tránh dính tuyến cũ.", "warning");
      resetList();
      if (typeof window.renderRouteMap === "function") await window.renderRouteMap([], mapId);
      setLoading(false);
    }
  }

  btnDi.addEventListener("click", () => loadStops("DI"));
  btnVe.addEventListener("click", () => loadStops("VE"));

  loadStops(currentDir);
});
