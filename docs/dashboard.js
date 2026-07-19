/**
 * dashboard.js — Mirage League Build Meta Dashboard
 *
 * Loads processed.json and renders a Chart.js line chart with per-skill
 * DPS over league time windows. Includes skill selector chips, custom
 * tooltips, and a sortable detail table.
 */

// Tableau-20 color palette — 20 distinct, accessible colors
const COLORS = [
  "#4e79a7", "#f28e2c", "#e15759", "#76b7b2", "#59a14f",
  "#edc949", "#af7aa1", "#ff9da7", "#9c755f", "#bab0ab",
  "#86bcb6", "#fdae61", "#b07aa1", "#d37295", "#a0cbe8",
  "#8cd17d", "#b6992d", "#499894", "#d4a0cd", "#f1ce63",
];

let state = null;    // full processed.json
let chart = null;    // Chart.js instance
let selectedSkills = new Set();
let selectedView = "t0_t1_cap";
let _hoveredDs = -1;
let sortColumn = "latestDps";
let sortDir = "desc";

function currentSkills() {
  return (state.views && state.views[selectedView] && state.views[selectedView].skills) || state.skills || {};
}
// ─── Initialisation ────────────────────────────────────────────────────

async function init() {
  try {
    const resp = await fetch("processed.json");
    if (!resp.ok) throw new Error(`HTTP ${resp.status}: ${resp.statusText}`);
    state = await resp.json();
  } catch (err) {
    showError(`Failed to load data: ${err.message}. Make sure processed.json exists.`);
    return;
  }

  if (!state.windows || state.windows.length === 0) {
    showError("No data available. Run the data pipeline first:<br><code>python src/fetch_index_state.py && python src/fetch_economy.py && python src/process.py</code>");
    return;
  }

  renderFiltersBar();
  renderAscendancyFilter();
  renderTimeFilters();

  const viewSel = document.getElementById("viewFilter");
  viewSel.value = state.default_view || "t0_t1_cap";
  selectedView = viewSel.value;

  viewSel.addEventListener("change", () => {
    selectedView = viewSel.value;
    selectedSkills.clear();
    renderSkillChips();
    selectDefaultSkills();
    renderChart();
    renderTable();
  });
  renderSkillChips();
  selectDefaultSkills();
  renderChart();
  renderTable();
}

function showError(msg) {
  const el = document.getElementById("errorBanner");
  el.innerHTML = msg;
  el.classList.add("visible");
}

// ─── Filters Bar ───────────────────────────────────────────────────────

function renderFiltersBar() {
  const fa = state.filters_applied || {};
  const el = document.getElementById("filtersBar");
  el.innerHTML = `
    <span>Excluding <strong>${fa.excluded_count || 0}</strong> T0/T1 uniques</span>
    <span>Divine cap: <strong>${fa.divine_cap_formula || "3 divines × league_day"}</strong></span>
    <span class="badge warn">⚠ Prices: time-matched from Keepers dump</span>
  `;
}

// ─── Ascendancy Filter ──────────────────────────────────────────────────

let selectedAscendancy = "";  // "" = all

function renderAscendancyFilter() {
  const select = document.getElementById("ascendancyFilter");
  const ascSkills = state.ascendancy_skills || {};
  const ascendancies = Object.keys(ascSkills).sort();

  select.innerHTML = '<option value="">All Ascendancies</option>' +
    ascendancies.map(a => `<option value="${escapeHtml(a)}">${escapeHtml(a)} (${ascSkills[a].length})</option>`).join("");

  select.value = selectedAscendancy;

  select.addEventListener("change", () => {
    selectedAscendancy = select.value;
    selectedSkills.clear();
    renderSkillChips();
    selectDefaultSkills();
    renderChart();
    renderTable();
  });
}

// ─── Time Range Filter ──────────────────────────────────────────────────

function filteredWindows() {
  const all = state.windows || [];
  const start = document.getElementById("timeStart").value;
  const end = document.getElementById("timeEnd").value;
  if (!start && !end) return all;
  const si = start ? all.indexOf(start) : 0;
  const ei = end ? all.indexOf(end) : all.length - 1;
  return all.slice(Math.max(0, si), ei + 1);
}

function renderTimeFilters() {
  const windows = state.windows || [];
  const startSel = document.getElementById("timeStart");
  const endSel = document.getElementById("timeEnd");

  startSel.innerHTML = windows.map(w => `<option value="${w}">${w}</option>`).join("");
  endSel.innerHTML = windows.map(w => `<option value="${w}">${w}</option>`).join("");

  // Default: first → last
  startSel.value = windows[0] || "";
  endSel.value = windows[windows.length - 1] || "";

  const onChange = () => {
    // Ensure start ≤ end
    const si = windows.indexOf(startSel.value);
    const ei = windows.indexOf(endSel.value);
    if (si > ei && ei >= 0) {
      endSel.value = startSel.value;
    }
    selectedSkills.clear();
    renderSkillChips();
    selectDefaultSkills();
    renderChart();
    renderTable();
  };

  startSel.addEventListener("change", onChange);
  endSel.addEventListener("change", onChange);
}

// ─── Skill Chips ───────────────────────────────────────────────────────

function renderSkillChips() {
  const container = document.getElementById("skillChips");
  const sorted = sortedSkillNames();

  container.innerHTML = sorted.map((name, i) => {
    const color = COLORS[i % COLORS.length];
    return `<span class="skill-chip" data-skill="${escapeHtml(name)}" style="--chip-color: ${color}">
      <span class="swatch" style="display:inline-block;width:10px;height:10px;border-radius:2px;background:${color}"></span>
      ${escapeHtml(name)}
    </span>`;
  }).join("");

  updateChipVisuals();
}

// Attach click handler once on the container (event delegation)
document.getElementById("skillChips").addEventListener("click", (e) => {
  const chip = e.target.closest(".skill-chip");
  if (!chip) return;
  toggleSkill(chip.dataset.skill);
});

function sortedSkillNames() {
  const skills = currentSkills();
  const fw = filteredWindows();
  const ascSkills = state.ascendancy_skills || {};

  // Walk backwards through the filtered range to find the last window
  // that actually has DPS data — many late windows have zero entries
  let latest = "";
  for (let i = fw.length - 1; i >= 0; i--) {
    const w = fw[i];
    for (const skill of Object.values(skills)) {
      const d = skill.dps_over_time && skill.dps_over_time[w];
      if (d && d > 0) {
        latest = w;
        break;
      }
    }
    if (latest) break;
  }
  if (!latest) latest = fw[fw.length - 1] || "";

  return Object.entries(skills)
    .filter(([name]) => {
      if (!selectedAscendancy) return true;
      const skillsForAsc = (ascSkills[selectedAscendancy] || []).map(s => s.toLowerCase());
      return skillsForAsc.includes(name.toLowerCase());
    })
    .sort((a, b) => {
      const dpsA = a[1].dps_over_time[latest] || 0;
      const dpsB = b[1].dps_over_time[latest] || 0;
      return dpsB - dpsA;
    })
    .map(([name]) => name);
}

function selectDefaultSkills() {
  const sorted = sortedSkillNames();
  const top8 = sorted.slice(0, 8);
  top8.forEach(s => selectedSkills.add(s));
  updateChipVisuals();
}

function toggleSkill(name) {
  if (selectedSkills.has(name)) {
    selectedSkills.delete(name);
  } else {
    selectedSkills.add(name);
  }
  updateChipVisuals();
  renderChart();
}

function updateChipVisuals() {
  document.querySelectorAll(".skill-chip").forEach(chip => {
    const name = chip.dataset.skill;
    chip.classList.toggle("selected", selectedSkills.has(name));
  });
}

// ─── Chart ─────────────────────────────────────────────────────────────

function renderChart() {
  const ctx = document.getElementById("dpsChart").getContext("2d");
  const windows = filteredWindows();
  const sorted = sortedSkillNames().filter(s => selectedSkills.has(s));

  const datasets = sorted.map((name, i) => {
    const skill = currentSkills()[name];
    const dpsData = skill.dps_over_time || {};
    const isHovered = _hoveredDs === -1 || _hoveredDs === i;

    return {
      label: name,
      data: windows.map(w => dpsData[w] ?? NaN),
      borderColor: COLORS[i % COLORS.length],
      backgroundColor: COLORS[i % COLORS.length] + "22",
      borderWidth: isHovered ? 2.5 : 0.6,
      pointRadius: isHovered ? 2 : 0,
      pointHoverRadius: 5,
      pointBackgroundColor: COLORS[i % COLORS.length],
      tension: 0.3,
      spanGaps: false,
      order: isHovered ? 0 : 1,
    };
  }).sort((a, b) => a.order - b.order);

  if (chart) {
    chart.data.labels = windows;
    chart.data.datasets = datasets;
    chart.update();
    return;
  }

  chart = new Chart(ctx, {
    type: "line",
    data: {
      labels: windows,
      datasets,
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      animation: false,
      interaction: {
        mode: "nearest",
        intersect: false,
      },
      onHover: (event, elements) => {
        const idx = elements.length > 0 ? elements[0].datasetIndex : -1;
        if (idx !== _hoveredDs) {
          _hoveredDs = idx;
          chart.update('none');
        }
      },
      plugins: {
        legend: {
          position: "top",
          labels: {
            color: "#c8d6e5",
            usePointStyle: true,
            pointStyleWidth: 10,
            font: { size: 12 },
            generateLabels: (c) => {
              const ds = c.data.datasets;
              return ds.map((d, i) => ({
                text: d.label,
                fillStyle: d.borderColor,
                hidden: false,
                index: i,
                fontColor: (_hoveredDs === -1 || _hoveredDs === i) ? "#c8d6e5" : "#4a5568",
                lineWidth: (_hoveredDs === -1 || _hoveredDs === i) ? 2.5 : 0.6,
              }));
            },
          },
          onHover: (e) => {
            e.native.target.style.cursor = "pointer";
          },
          onLeave: () => {
            _hoveredDs = -1;
            chart.update('none');
          },
        },
        tooltip: {
          enabled: false,
          external: handleTooltip,
        },
      },
        scales: {
          x: {
            title: { display: true, text: "League Time Window", color: "#6c7a8d" },
            ticks: { color: "#6c7a8d", maxTicksLimit: 30, font: { size: 10 } },
            grid: { color: "#1a1f2b" },
          },
          y: {
            title: { display: true, text: "Top-20 Average DPS", color: "#6c7a8d" },
            ticks: { color: "#6c7a8d", callback: v => fmtNum(v) },
            grid: { color: "#1a1f2b" },
            beginAtZero: false,
          },
        },
      },
    });
  }

function handleTooltip(context) {
  const { chart: ch, tooltip } = context;
  let tipEl = document.getElementById("chartjs-tooltip");

  if (!tipEl) {
    tipEl = document.createElement("div");
    tipEl.id = "chartjs-tooltip";
    tipEl.style.cssText = `
      position: absolute; pointer-events: none;
      background: #121620; border: 1px solid #2a3040; border-radius: 6px;
      padding: 10px 14px; font-size: 0.8rem; color: #c8d6e5;
      max-width: 300px; z-index: 9999; box-shadow: 0 4px 12px rgba(0,0,0,0.5);
    `;
    ch.canvas.parentNode.appendChild(tipEl);
  }

  if (tooltip.opacity === 0) {
    tipEl.style.opacity = "0";
    return;
  }

  const dataPoint = tooltip.dataPoints[0];
  if (!dataPoint) { tipEl.style.opacity = "0"; return; }

  const ds = dataPoint.dataset;
  const skillName = ds.label;
  const windowLabel = ch.data.labels[dataPoint.dataIndex];
  const dps = dataPoint.raw;
  const skillData = currentSkills()[skillName];
  const topAsc = (skillData.top_ascendancy || {})[windowLabel] || "—";
  const ascCounts = (skillData.ascendancy_counts || {})[windowLabel] || {};
  const topAscCount = ascCounts[topAsc] || 0;

  // Top 3 uniques
  const uniques = (skillData.unique_usage || {})[windowLabel] || {};
  const topUniques = Object.entries(uniques)
    .sort((a, b) => b[1].count - a[1].count)
    .slice(0, 3);

  let uniquesHtml = "";
  if (topUniques.length > 0) {
    uniquesHtml = "<div style='margin-top:6px;font-size:0.75rem;color:#6c7a8d'>Top Uniques:</div>" +
      topUniques.map(([name, data]) => {
        const price = data.avg_price_chaos > 0
          ? `${fmtNum(data.avg_price_chaos)}c`
          : data.divine_value > 0
            ? fmtNum(data.divine_value) + "div"
            : "—";
        return `<div style="font-size:0.75rem;margin-left:4px">• ${escapeHtml(name)} ×${data.count} (${price})</div>`;
      }).join("");
  }

  tipEl.innerHTML = `
    <div style="font-weight:600;color:#fff;margin-bottom:4px">${escapeHtml(skillName)}</div>
    <div><span style="color:#6c7a8d">${windowLabel}</span> | DPS: <strong>${fmtNum(dps)}</strong></div>
    <div style="margin-top:4px">
      <span style="color:#6c7a8d">Top Ascendancy:</span> ${escapeHtml(topAsc)} (${topAscCount})
    </div>
    <div><span style="color:#6c7a8d">Filtered out:</span> ${filteredOut}</div>
    ${uniquesHtml}
  `;

  // Position the tooltip
  const pos = ch.canvas.getBoundingClientRect();
  const top = pos.top + window.scrollY + tooltip.caretY - tipEl.offsetHeight - 10;
  const left = pos.left + window.scrollX + tooltip.caretX - tipEl.offsetWidth / 2;

  tipEl.style.opacity = "1";
  tipEl.style.top = Math.max(0, top) + "px";
  tipEl.style.left = Math.max(0, left) + "px";
}

function renderTable() {
  const tbody = document.getElementById("skillTableBody");
  const skills = currentSkills();
  const fw = filteredWindows();

  // Find the last window in range that has actual DPS data
  let latest = "";
  for (let i = fw.length - 1; i >= 0; i--) {
    const w = fw[i];
    for (const skill of Object.values(skills)) {
      const d = skill.dps_over_time && skill.dps_over_time[w];
      if (d && d > 0) {
        latest = w;
        break;
      }
    }
    if (latest) break;
  }
  if (!latest) latest = fw[fw.length - 1] || "";

  // Compute row data
  let rows = Object.entries(skills).map(([name, data]) => {
    const latestDps = data.dps_over_time[latest] || 0;
    const topAsc = data.top_ascendancy[latest] || "—";

    // Top 3 uniques for latest window
    const uniques = data.unique_usage[latest] || {};
    const top3 = Object.entries(uniques)
      .sort((a, b) => b[1].count - a[1].count)
      .slice(0, 3)
      .map(([itemName, d]) => `${escapeHtml(itemName)} ×${d.count}`)
      .join(", ");

    return { name, latestDps, topAsc, top3 };
  });

  // Sort
  rows.sort((a, b) => {
    let cmp = 0;
    switch (sortColumn) {
      case "name": cmp = a.name.localeCompare(b.name); break;
      case "latestDps": cmp = a.latestDps - b.latestDps; break;
      case "dominant": cmp = a.topAsc.localeCompare(b.topAsc); break;
      default: cmp = a.latestDps - b.latestDps;
    }
    return sortDir === "asc" ? cmp : -cmp;
  });

  tbody.innerHTML = rows.map(r => `
    <tr>
      <td>${escapeHtml(r.name)}</td>
      <td>${fmtNum(r.latestDps)}</td>
      <td>${escapeHtml(r.topAsc)}</td>
      <td style="font-size:0.8rem;color:#6c7a8d">${r.top3 || "—"}</td>
    </tr>
  `).join("");

  // Update sort header indicators
  document.querySelectorAll("th").forEach(th => {
    th.classList.toggle("sorted", th.dataset.sort === sortColumn);
    const arrow = th.querySelector(".arrow");
    if (arrow) {
      arrow.textContent = th.dataset.sort === sortColumn
        ? (sortDir === "asc" ? "▲" : "▼") : "";
    }
  });
}

document.getElementById("skillTable").addEventListener("click", (e) => {
  const th = e.target.closest("th");
  if (!th || !th.dataset.sort) return;
  const col = th.dataset.sort;
  if (sortColumn === col) {
    sortDir = sortDir === "asc" ? "desc" : "asc";
  } else {
    sortColumn = col;
    sortDir = "desc";
  }
  renderTable();
});

// ─── Utilities ─────────────────────────────────────────────────────────

function fmtNum(n) {
  if (n == null || isNaN(n)) return "—";
  if (n >= 1e9) return (n / 1e9).toFixed(1) + "B";
  if (n >= 1e6) return (n / 1e6).toFixed(1) + "M";
  if (n >= 1e3) return (n / 1e3).toFixed(1) + "k";
  return Number.isInteger(n) ? n.toString() : n.toFixed(1);
}

function escapeHtml(str) {
  const div = document.createElement("div");
  div.textContent = str;
  return div.innerHTML;
}

// ─── Start ─────────────────────────────────────────────────────────────

init();