// Use the deployed Azure Function route exactly as defined in the backend.
const API_URL = "https://project2functionapp.azurewebsites.net/api/getDietData";

function createFallbackDataset() {
  return {
    diets: ["Vegan", "Keto", "Paleo"],
    protein: [45, 70, 60],
    carbs: [60, 20, 35],
    fat: [20, 80, 55],
    correlations: [
      [1.0, 0.3, 0.65],
      [0.3, 1.0, 0.1],
      [0.65, 0.1, 1.0]
    ],
    metrics: ["Protein(g)", "Carbs(g)", "Fat(g)"],
    meta: {
      timestamp: new Date().toISOString(),
      executionTimeMs: 120,
      recordCount: 3
    }
  };
}

let lastDataset = null;

function showStatus(msg, kind = "info") {
  const el = document.getElementById("status");
  if (!el) return;
  el.className = "fixed bottom-4 right-4 text-sm px-3 py-2 rounded shadow transition-opacity";
  const colors = {
    info: "bg-gray-900 text-white",
    success: "bg-green-600 text-white",
    error: "bg-red-600 text-white"
  };
  el.classList.add(...colors[kind].split(" "));
  el.textContent = msg;
  el.style.opacity = "1";
  el.classList.remove("hidden");
  clearTimeout(el._hideTimer);
  el._hideTimer = setTimeout(() => {
    el.style.opacity = "0";
  }, 2400);
}

function renderMeta({ executionTimeMs, timestamp, recordCount } = {}) {
  const el = document.getElementById("meta");
  if (!el) return;
  el.innerHTML = `
    <p><span class="font-semibold">Last Run:</span> ${timestamp ?? "-"}</p>
    <p><span class="font-semibold">Execution Time:</span> ${executionTimeMs != null ? executionTimeMs + " ms" : "-"}</p>
    <p><span class="font-semibold">Records:</span> ${recordCount ?? "-"}</p>
  `;
}

let barChart;
let pieChart;
let scatterChart;

function buildOrUpdateBar(labels, protein) {
  const ctx = document.getElementById("barChart");
  const cfg = {
    type: "bar",
    data: {
      labels,
      datasets: [{
        label: "Protein (g)",
        data: protein,
        backgroundColor: "rgba(59, 130, 246, 0.7)"
      }]
    },
    options: {
      responsive: true,
      plugins: {
        title: { display: true, text: "Average Protein by Diet Type" },
        legend: { display: true }
      },
      scales: {
        y: {
          title: { display: true, text: "Grams" },
          ticks: { precision: 0 }
        }
      }
    }
  };

  if (!barChart) {
    barChart = new Chart(ctx, cfg);
    return;
  }

  barChart.data.labels = labels;
  barChart.data.datasets[0].data = protein;
  barChart.update();
}

function buildOrUpdatePie(labels, carbs) {
  const ctx = document.getElementById("pieChart");
  const cfg = {
    type: "pie",
    data: {
      labels,
      datasets: [{
        data: carbs,
        backgroundColor: ["#22c55e", "#f97316", "#8b5cf6", "#06b6d4", "#f43f5e"]
      }]
    },
    options: {
      responsive: true,
      plugins: { title: { display: true, text: "Carbohydrate Distribution" } }
    }
  };

  if (!pieChart) {
    pieChart = new Chart(ctx, cfg);
    return;
  }

  pieChart.data.labels = labels;
  pieChart.data.datasets[0].data = carbs;
  pieChart.update();
}

function buildOrUpdateScatter(carbs, protein) {
  const ctx = document.getElementById("scatterPlot");
  const points = carbs.map((c, i) => ({ x: c, y: protein[i] }));
  const cfg = {
    type: "scatter",
    data: {
      datasets: [{
        label: "Protein vs Carbs",
        data: points,
        backgroundColor: "rgba(239, 68, 68, 0.8)"
      }]
    },
    options: {
      responsive: true,
      plugins: { title: { display: true, text: "Protein vs Carbohydrates" } },
      scales: {
        x: { title: { display: true, text: "Carbs (g)" } },
        y: { title: { display: true, text: "Protein (g)" } }
      }
    }
  };

  if (!scatterChart) {
    scatterChart = new Chart(ctx, cfg);
    return;
  }

  scatterChart.data.datasets[0].data = points;
  scatterChart.update();
}

function buildOrUpdateHeatmap(matrix, labels) {
  const container = document.getElementById("heatmap");
  if (!container) return;

  container.innerHTML = "";
  container.className = "w-full h-48 overflow-auto";

  const size = labels.length;
  const grid = document.createElement("div");
  grid.style.display = "grid";
  grid.style.gridTemplateColumns = `max-content repeat(${size}, 1fr)`;
  grid.style.gap = "4px";
  grid.style.alignItems = "center";

  const colorFor = value => {
    const clamped = Math.max(0, Math.min(1, value));
    const r = Math.round(255 - clamped * 155);
    const g = Math.round(255 - clamped * 60);
    const b = Math.round(255 - clamped * 205);
    return `rgb(${r},${g},${b})`;
  };

  const emptyCorner = document.createElement("div");
  emptyCorner.textContent = "";
  emptyCorner.style.fontWeight = "600";
  emptyCorner.style.padding = "4px 8px";
  grid.appendChild(emptyCorner);

  labels.forEach(label => {
    const cell = document.createElement("div");
    cell.textContent = label;
    cell.style.fontWeight = "600";
    cell.style.fontSize = "12px";
    cell.style.padding = "4px 8px";
    grid.appendChild(cell);
  });

  for (let rowIndex = 0; rowIndex < size; rowIndex += 1) {
    const rowLabel = document.createElement("div");
    rowLabel.textContent = labels[rowIndex];
    rowLabel.style.fontWeight = "600";
    rowLabel.style.fontSize = "12px";
    rowLabel.style.padding = "4px 8px";
    grid.appendChild(rowLabel);

    for (let colIndex = 0; colIndex < size; colIndex += 1) {
      const value = matrix[rowIndex][colIndex];
      const cell = document.createElement("div");
      cell.title = `${labels[rowIndex]} vs ${labels[colIndex]}: ${value.toFixed(2)}`;
      cell.style.background = colorFor(value);
      cell.style.height = "28px";
      cell.style.borderRadius = "6px";
      cell.style.display = "flex";
      cell.style.alignItems = "center";
      cell.style.justifyContent = "center";
      cell.style.fontSize = "11px";
      cell.style.color = value > 0.6 ? "#fff" : "#111";
      cell.textContent = value.toFixed(2);
      grid.appendChild(cell);
    }
  }

  container.appendChild(grid);
}

function renderAllFrom(data) {
  buildOrUpdateBar(data.diets, data.protein);
  buildOrUpdatePie(data.diets, data.carbs);
  buildOrUpdateScatter(data.carbs, data.protein);
  buildOrUpdateHeatmap(data.correlations, data.metrics);
  renderMeta(data.meta);
}

function normalizeBackendPayload(data) {
  const dietRows = Array.isArray(data?.diets) ? data.diets : [];
  const proteinRows = Array.isArray(data?.protein) ? data.protein : [];
  const carbRows = Array.isArray(data?.carbs) ? data.carbs : [];
  const fatRows = Array.isArray(data?.fat) ? data.fat : [];

  const diets = proteinRows.length
    ? proteinRows.map(item => item["Diet_type"])
    : dietRows.map(item => item["Diet_type"]);
  const protein = proteinRows.map(item => Number(item["Protein(g)"] ?? 0));
  const carbs = carbRows.map(item => Number(item["Carbs(g)"] ?? 0));
  const fat = fatRows.map(item => Number(item["Fat(g)"] ?? 0));

  const metrics = data?.correlations
    ? Object.keys(data.correlations)
    : ["Protein(g)", "Carbs(g)", "Fat(g)"];

  const correlations = metrics.map(rowKey =>
    metrics.map(colKey => Number(data?.correlations?.[rowKey]?.[colKey] ?? 0))
  );

  return {
    diets,
    protein,
    carbs,
    fat,
    correlations,
    metrics,
    meta: data?.meta ?? {
      timestamp: new Date().toISOString(),
      executionTimeMs: null,
      recordCount: diets.length
    }
  };
}

async function fetchInsights() {
  if (API_URL.includes("<YOUR-FUNCTION-APP>")) {
    showStatus("Set the deployed Azure Function URL first", "error");
    return;
  }

  try {
    showStatus("Loading...", "info");
    const res = await fetch(API_URL, { headers: { Accept: "application/json" } });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);

    const data = await res.json();
    lastDataset = normalizeBackendPayload(data);
    renderAllFrom(lastDataset);
    showStatus("Updated", "success");
  } catch (err) {
    console.error(err);
    if (!lastDataset) {
      lastDataset = createFallbackDataset();
      renderAllFrom(lastDataset);
    }
    showStatus(`Failed to load insights: ${err.message}`, "error");
  }
}

const refreshBtn = document.getElementById("refreshData");
if (refreshBtn) {
  refreshBtn.addEventListener("click", fetchInsights);
}

fetchInsights();
