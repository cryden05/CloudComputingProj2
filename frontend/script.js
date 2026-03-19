// ------------------------------
// Mock Data (used until API is ready)
// ------------------------------
const mockData = {
  diets: ["Vegan", "Keto", "Paleo"],
  protein: [45, 70, 60],
  carbs: [60, 20, 35],
  fat: [20, 80, 55],
  // simple 3x3 correlation matrix for the heatmap (protein, carbs, fat)
  correlations: [
    [1.00, 0.30, 0.65], // protein vs (protein, carbs, fat)
    [0.30, 1.00, 0.10], // carbs
    [0.65, 0.10, 1.00]  // fat
  ],
  metrics: ["Protein", "Carbs", "Fat"]
};

// Keep the last dataset so filters/refresh can reuse it later
let lastDataset = {
  diets: [...mockData.diets],
  protein: [...mockData.protein],
  carbs: [...mockData.carbs],
  fat: [...mockData.fat],
  correlations: mockData.correlations.map(row => [...row]),
  metrics: [...mockData.metrics],
  meta: {
    timestamp: new Date().toISOString(),
    executionTimeMs: 120,
    recordCount: mockData.diets.length
  }
};

// ------------------------------
// Status & Metadata helpers
// ------------------------------
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
  el._hideTimer = setTimeout(() => { el.style.opacity = "0"; }, 1800);
}

function renderMeta({ executionTimeMs, timestamp, recordCount } = {}) {
  const el = document.getElementById("meta");
  if (!el) return;
  el.innerHTML = `
    <p><span class="font-semibold">Last Run:</span> ${timestamp ?? "—"}</p>
    <p><span class="font-semibold">Execution Time:</span> ${executionTimeMs != null ? executionTimeMs + " ms" : "—"}</p>
    <p><span class="font-semibold">Records:</span> ${recordCount ?? "—"}</p>
  `;
}

// ------------------------------
// Chart builders (create or update)
// ------------------------------
let barChart, pieChart, scatterChart;

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
      plugins: { title: { display: true, text: "Average Protein by Diet Type" }, legend: { display: true } },
      scales: {
        y: {
          title: { display: true, text: "Grams" },
          ticks: { precision: 0 }
        }
      }
    }
  };
  if (!barChart) barChart = new Chart(ctx, cfg);
  else {
    barChart.data.labels = labels;
    barChart.data.datasets[0].data = protein;
    barChart.update();
  }
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
  if (!pieChart) pieChart = new Chart(ctx, cfg);
  else {
    pieChart.data.labels = labels;
    pieChart.data.datasets[0].data = carbs;
    pieChart.update();
  }
}

function buildOrUpdateScatter(carbs, protein) {
  const ctx = document.getElementById("scatterPlot");
  const points = carbs.map((c, i) => ({ x: c, y: protein[i] }));
  const cfg = {
    type: "scatter",
    data: { datasets: [{ label: "Protein vs Carbs", data: points, backgroundColor: "rgba(239, 68, 68, 0.8)" }] },
    options: {
      responsive: true,
      plugins: { title: { display: true, text: "Protein vs Carbohydrates" } },
      scales: {
        x: { title: { display: true, text: "Carbs (g)" } },
        y: { title: { display: true, text: "Protein (g)" } }
      }
    }
  };
  if (!scatterChart) scatterChart = new Chart(ctx, cfg);
  else {
    scatterChart.data.datasets[0].data = points;
    scatterChart.update();
  }
}

// ------------------------------
// Heatmap (no extra libs) — renders into #heatmap
// ------------------------------
function buildOrUpdateHeatmap(matrix, labels) {
  const container = document.getElementById("heatmap");
  if (!container) return;

  // Clear previous content
  container.innerHTML = "";

  // Basic styles
  container.className = "w-full h-48 overflow-auto";

  // Create a grid using CSS
  const size = labels.length;
  const grid = document.createElement("div");
  grid.style.display = "grid";
  grid.style.gridTemplateColumns = `max-content repeat(${size}, 1fr)`;
  grid.style.gap = "4px";
  grid.style.alignItems = "center";

  // Color scale helper: value ∈ [0,1] -> from white to teal
  const colorFor = (v) => {
    const clamped = Math.max(0, Math.min(1, v));
    const r = Math.round(255 - clamped * 155); // 255 -> 100
    const g = Math.round(255 - clamped * 60);  // 255 -> 195
    const b = Math.round(255 - clamped * 205); // 255 -> 50
    return `rgb(${r},${g},${b})`;
  };

  // Header row (top-left empty, then metric labels)
  const emptyCorner = document.createElement("div");
  emptyCorner.textContent = "";
  emptyCorner.style.fontWeight = "600";
  emptyCorner.style.padding = "4px 8px";
  grid.appendChild(emptyCorner);

  labels.forEach(l => {
    const cell = document.createElement("div");
    cell.textContent = l;
    cell.style.fontWeight = "600";
    cell.style.fontSize = "12px";
    cell.style.padding = "4px 8px";
    grid.appendChild(cell);
  });

  // Rows: label + colored cells
  for (let r = 0; r < size; r++) {
    const rowLabel = document.createElement("div");
    rowLabel.textContent = labels[r];
    rowLabel.style.fontWeight = "600";
    rowLabel.style.fontSize = "12px";
    rowLabel.style.padding = "4px 8px";
    grid.appendChild(rowLabel);

    for (let c = 0; c < size; c++) {
      const v = matrix[r][c]; // expected 0..1 (1.0 on diagonal)
      const cell = document.createElement("div");
      cell.title = `${labels[r]} vs ${labels[c]}: ${v.toFixed(2)}`;
      cell.style.background = colorFor(v);
      cell.style.height = "28px";
      cell.style.borderRadius = "6px";
      cell.style.display = "flex";
      cell.style.alignItems = "center";
      cell.style.justifyContent = "center";
      cell.style.fontSize = "11px";
      cell.style.color = v > 0.6 ? "#fff" : "#111";
      cell.textContent = v.toFixed(2);
      grid.appendChild(cell);
    }
  }

  container.appendChild(grid);
}

// ------------------------------
// Bootstrap with mock data
// ------------------------------
function renderAllFrom(data) {
  buildOrUpdateBar(data.diets, data.protein);
  buildOrUpdatePie(data.diets, data.carbs);
  buildOrUpdateScatter(data.carbs, data.protein);
  buildOrUpdateHeatmap(data.correlations, data.metrics);
  renderMeta(data.meta);
}

renderAllFrom(lastDataset);

// ------------------------------
// Refresh button: simulate new data now; call API later
// ------------------------------
const refreshBtn = document.getElementById("refreshData");
if (refreshBtn) {
  refreshBtn.addEventListener("click", async () => {
    // For now: simulate a refresh (mock jitter). Later: call fetchInsights()
    showStatus("Refreshing…");
    const jitter = () => Math.max(0, Math.round((Math.random() * 10) - 5));
    const refreshed = {
      ...lastDataset,
      protein: lastDataset.protein.map(v => Math.max(0, v + jitter())),
      carbs: lastDataset.carbs.map(v => Math.max(0, v + jitter())),
      // lightly wiggle correlations towards/within [0,1]
      correlations: lastDataset.correlations.map(row =>
        row.map(v => Math.max(0, Math.min(1, v + (Math.random() - 0.5) * 0.05)))
      ),
      meta: {
        timestamp: new Date().toISOString(),
        executionTimeMs: 80 + Math.floor(Math.random() * 120),
        recordCount: lastDataset.diets.length
      }
    };
    lastDataset = refreshed;
    renderAllFrom(lastDataset);
    showStatus("Updated", "success");
  });
}

// ------------------------------
// API integration (replace URL and call fetchInsights() instead of mock)
// ------------------------------
async function fetchInsights() {
  const url = "https://<YOUR-FUNCTION-APP>.azurewebsites.net/api/insights"; // Replace when backend is ready
  try {
    showStatus("Loading…");
    const res = await fetch(url, { headers: { "Accept": "application/json" } });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();

    // Expected payload shape:
    // {
    //   diets: string[],
    //   protein: number[],
    //   carbs: number[],
    //   fat?: number[],
    //   correlations?: number[][], // values 0..1
    //   metrics?: string[],        // labels for correlations
    //   meta: { timestamp, executionTimeMs, recordCount }
    // }

    if (!data?.diets || !data?.protein || !data?.carbs) throw new Error("Unexpected payload");

    // Provide defaults for heatmap if backend doesn’t return them
    if (!data.correlations || !data.metrics) {
      data.metrics = ["Protein", "Carbs", "Fat"];
      data.correlations = [
        [1.00, 0.30, 0.65],
        [0.30, 1.00, 0.10],
        [0.65, 0.10, 1.00]
      ];
    }

    lastDataset = data;
    renderAllFrom(lastDataset);
    showStatus("Updated", "success");
  } catch (err) {
    console.error(err);
    showStatus("Failed to load insights", "error");
  }
}

// If you want to use the API immediately, swap the click handler to:
// refreshBtn?.removeEventListener("click", ...); // remove old if needed
// refreshBtn?.addEventListener("click", fetchInsights);