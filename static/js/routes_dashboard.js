// static/js/routes_dashboard.js
// Trang /routes: hiển thị KPI tổng quan, không render bản đồ tại đây.

document.addEventListener("DOMContentLoaded", () => {
  const sel = document.getElementById("routeSelect");
  const search = document.getElementById("routeSearch");
  const tbody = document.getElementById("routeTableBody");
  const empty = document.getElementById("emptyState");
  const countEl = document.getElementById("routeCount");

  const titleEl = document.getElementById("selectedRouteTitle");
  const metaEl = document.getElementById("selectedRouteMeta");
  const statusEl = document.getElementById("kpiDataStatus");
  const kpiStopsDI = document.getElementById("kpiStopsDI");
  const kpiStopsVE = document.getElementById("kpiStopsVE");
  const kpiStopsDIGeo = document.getElementById("kpiStopsDIGeo");
  const kpiStopsVEGeo = document.getElementById("kpiStopsVEGeo");
  const kpiGeoPercent = document.getElementById("kpiGeoPercent");
  const errorAlert = document.getElementById("routeSummaryError");
  const chipContainer = document.getElementById("statusChips");
  const badgeDI = document.getElementById("badgeDI");
  const badgeVE = document.getElementById("badgeVE");

  const btnDetail = document.getElementById("btnRouteDetail");

  if (!tbody) return;

  let requestSeq = 0;

  function escapeHtml(str) {
    return String(str ?? "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/\"/g, "&quot;")
      .replace(/'/g, "&#039;");
  }

  function setInfoFromRow(row) {
    const code = row?.dataset?.code || "";
    const name = row?.dataset?.name || "";
    const start = row?.dataset?.start || "";
    const end = row?.dataset?.end || "";

    if (titleEl) titleEl.textContent = code ? `Tuyến ${code} — ${name || "—"}` : (name || "—");
    if (metaEl) metaEl.textContent = (start || end) ? `${start || "—"} → ${end || "—"}` : "—";
  }

  function setDetailLink(routeId) {
    if (!btnDetail) return;
    btnDetail.href = routeId ? `/routes/${routeId}` : "#";
    btnDetail.classList.toggle("disabled", !routeId);
  }

  function resetSummary() {
    if (kpiStopsDI) kpiStopsDI.textContent = "0 trạm";
    if (kpiStopsVE) kpiStopsVE.textContent = "0 trạm";
    if (kpiStopsDIGeo) kpiStopsDIGeo.textContent = "— tọa độ";
    if (kpiStopsVEGeo) kpiStopsVEGeo.textContent = "— tọa độ";
    if (kpiGeoPercent) kpiGeoPercent.textContent = "0%";
    if (badgeDI) badgeDI.className = "badge text-bg-secondary";
    if (badgeVE) badgeVE.className = "badge text-bg-secondary";
    if (statusEl) {
      statusEl.textContent = "—";
      statusEl.className = "badge text-bg-secondary";
    }
    if (errorAlert) errorAlert.classList.add("d-none");
  }

  function showLoading() {
    if (kpiStopsDI) kpiStopsDI.textContent = "…";
    if (kpiStopsVE) kpiStopsVE.textContent = "…";
    if (kpiStopsDIGeo) kpiStopsDIGeo.textContent = "Đang tải…";
    if (kpiStopsVEGeo) kpiStopsVEGeo.textContent = "Đang tải…";
    if (kpiGeoPercent) kpiGeoPercent.textContent = "…";
    if (statusEl) {
      statusEl.textContent = "…";
      statusEl.className = "badge text-bg-secondary";
    }
    if (errorAlert) errorAlert.classList.add("d-none");
  }

  function renderSummary(data) {
    if (!data) {
      resetSummary();
      return;
    }

    const di = data.directions?.DI || { stops: 0, with_geo: 0 };
    const ve = data.directions?.VE || { stops: 0, with_geo: 0 };

    if (kpiStopsDI) kpiStopsDI.textContent = `${di.stops} trạm`;
    if (kpiStopsVE) kpiStopsVE.textContent = `${ve.stops} trạm`;
    if (kpiStopsDIGeo) kpiStopsDIGeo.textContent = `${di.with_geo} tọa độ`;
    if (kpiStopsVEGeo) kpiStopsVEGeo.textContent = `${ve.with_geo} tọa độ`;
    if (kpiGeoPercent) kpiGeoPercent.textContent = `${data.totals?.percent_with_geo ?? 0}%`;

    if (statusEl) {
      const ok = data.data_status === "Đủ";
      statusEl.textContent = data.data_status || "—";
      statusEl.className = "badge " + (ok ? "text-bg-success" : "text-bg-warning");
    }

    if (badgeDI) {
      const ok = di.has_enough_shape ?? (di.stops >= 2 && di.with_geo >= 2);
      badgeDI.textContent = ok ? "OK" : "Thiếu";
      badgeDI.className = "badge " + (ok ? "text-bg-success" : "text-bg-warning");
    }
    if (badgeVE) {
      const ok = ve.has_enough_shape ?? (ve.stops >= 2 && ve.with_geo >= 2);
      badgeVE.textContent = ok ? "OK" : "Thiếu";
      badgeVE.className = "badge " + (ok ? "text-bg-success" : "text-bg-warning");
    }

    if (errorAlert) errorAlert.classList.add("d-none");
  }

  async function loadSummary(routeId) {
    if (!routeId) {
      resetSummary();
      setDetailLink(null);
      return;
    }

    requestSeq += 1;
    const seq = requestSeq;
    showLoading();

    try {
      const res = await fetch(`/api/routes/${routeId}/summary`);
      const data = await res.json();

      if (seq !== requestSeq) return; // đã có yêu cầu mới hơn

      if (!res.ok) throw new Error("API summary lỗi");

      renderSummary(data);
      setDetailLink(routeId);

       // cập nhật data-status cho filter chip
      const row = tbody.querySelector(`.route-row[data-route-id="${routeId}"]`);
      if (row && data?.data_status) {
        row.setAttribute("data-status", data.data_status === "Đủ" ? "DU" : "THIEU");
      }
    } catch (e) {
      if (seq !== requestSeq) return;
      console.error(e);
      resetSummary();
      if (errorAlert) errorAlert.classList.remove("d-none");
      setDetailLink(routeId);
    }
  }

  function highlight(routeId) {
    tbody.querySelectorAll(".route-row").forEach((r) => {
      r.classList.toggle("table-active", r.dataset.routeId === String(routeId));
    });
  }

  function selectByRouteId(routeId) {
    routeId = String(routeId);

    if (sel) sel.value = routeId;

    const row = tbody.querySelector(`.route-row[data-route-id="${routeId}"]`);
    if (row) setInfoFromRow(row);

    highlight(routeId);
    loadSummary(routeId);
  }

  tbody.addEventListener("click", (e) => {
    const row = e.target.closest(".route-row");
    if (!row) return;
    selectByRouteId(row.dataset.routeId);
  });

  if (sel) {
    sel.addEventListener("change", () => {
      if (sel.value) selectByRouteId(sel.value);
    });
  }

  function applyFilter() {
    const q = (search?.value || "").trim().toLowerCase();
    const filterStatus = chipContainer?.querySelector(".chip-filter.active")?.dataset?.filter || "";
    const rows = tbody.querySelectorAll(".route-row");
    let shown = 0;
    let firstShownId = null;

    rows.forEach((tr) => {
      const text = tr.getAttribute("data-text") || "";
      const rowStatus = (tr.getAttribute("data-status") || "").toUpperCase();
      const statusOk = !filterStatus || rowStatus === filterStatus;
      const ok = (!q || text.includes(q)) && statusOk;
      tr.style.display = ok ? "" : "none";
      if (ok) {
        shown += 1;
        if (!firstShownId) firstShownId = tr.dataset.routeId;
      }
    });

    if (countEl) countEl.textContent = String(shown);
    if (empty) empty.classList.toggle("d-none", shown !== 0);

    const currentId = sel?.value || tbody.querySelector(".route-row.table-active")?.dataset?.routeId;
    const currentRow = currentId ? tbody.querySelector(`.route-row[data-route-id="${currentId}"]`) : null;
    const currentVisible = currentRow && currentRow.style.display !== "none";

    if (!currentVisible && firstShownId) selectByRouteId(firstShownId);
  }

  if (search) search.addEventListener("input", applyFilter);
  if (chipContainer) {
    chipContainer.addEventListener("click", (e) => {
      const btn = e.target.closest(".chip-filter");
      if (!btn) return;
      chipContainer.querySelectorAll(".chip-filter").forEach((b) => b.classList.remove("active"));
      btn.classList.add("active");
      applyFilter();
    });
  }

  const initial = window.__initialRouteId != null ? String(window.__initialRouteId) : null;
  if (initial && tbody.querySelector(`.route-row[data-route-id="${initial}"]`)) {
    selectByRouteId(initial);
  } else if (sel && sel.value) {
    selectByRouteId(sel.value);
  } else {
    const first = tbody.querySelector(".route-row");
    if (first) selectByRouteId(first.dataset.routeId);
    else resetSummary();
  }

  applyFilter();
});
