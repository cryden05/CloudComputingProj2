const API_BASE_URL = localStorage.getItem("apiBaseUrl") || "https://project2functionapp.azurewebsites.net/api";
const TOKEN_KEY = "nutrition_dashboard_token";
const OAUTH_STATE_KEY = "nutrition_dashboard_oauth_state";
const INSIGHTS_API_PATH = "/getDietData";
const RECIPES_API_PATH = "/browseRecipes";

let authToken = localStorage.getItem(TOKEN_KEY) || "";
let currentUser = null;
let lastDataset = null;
let lastRecipePayload = null;
let barChart;
let pieChart;
let scatterChart;
let chartsInitialized = false;
const PREFERS_REDUCED_MOTION = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

const recipeState = {
  keyword: "",
  dietType: "all",
  page: 1,
  pageSize: 10
};

const elements = {
  authSection: document.getElementById("authSection"),
  dashboardSection: document.getElementById("dashboardSection"),
  userBar: document.getElementById("userBar"),
  userName: document.getElementById("userName"),
  authMessage: document.getElementById("authMessage"),
  status: document.getElementById("status"),
  meta: document.getElementById("meta"),
  refreshData: document.getElementById("refreshData"),
  showLogin: document.getElementById("showLogin"),
  showRegister: document.getElementById("showRegister"),
  loginForm: document.getElementById("loginForm"),
  registerForm: document.getElementById("registerForm"),
  logoutBtn: document.getElementById("logoutBtn"),
  githubLoginBtn: document.getElementById("githubLoginBtn"),
  apiEndpointLabel: document.getElementById("apiEndpointLabel"),
  avgProteinValue: document.getElementById("avgProteinValue"),
  avgCarbsValue: document.getElementById("avgCarbsValue"),
  avgFatValue: document.getElementById("avgFatValue"),
  recordCountValue: document.getElementById("recordCountValue"),
  keywordSearch: document.getElementById("keywordSearch"),
  dietTypeFilter: document.getElementById("dietTypeFilter"),
  pageSizeSelect: document.getElementById("pageSizeSelect"),
  searchRecipes: document.getElementById("searchRecipes"),
  clearFilters: document.getElementById("clearFilters"),
  recipeSummary: document.getElementById("recipeSummary"),
  recipeMeta: document.getElementById("recipeMeta"),
  recipeResults: document.getElementById("recipeResults"),
  paginationControls: document.getElementById("paginationControls"),
  showAllRecipesBtn: document.getElementById("showAllRecipesBtn"),
  refreshRecipesBtn: document.getElementById("refreshRecipesBtn"),
  recipeExplorerSection: document.getElementById("recipeExplorerSection"),
  showChartsBtn: document.getElementById("showChartsBtn"),
  renderChartsBtn: document.getElementById("renderChartsBtn"),
  chartsSection: document.getElementById("chartsSection"),
  chartsPlaceholder: document.getElementById("chartsPlaceholder"),
  chartsGrid: document.getElementById("chartsGrid")
};

const quickFilterButtons = Array.from(document.querySelectorAll("[data-quick-filter]"));

if (elements.apiEndpointLabel) {
  elements.apiEndpointLabel.textContent = `${API_BASE_URL}${RECIPES_API_PATH}`;
}

function apiUrl(path) {
  return `${API_BASE_URL}${path}`;
}

function createFallbackDataset() {
  return {
    diets: ["dash", "keto", "mediterranean", "paleo", "vegan"],
    dietCounts: [1745, 1512, 1753, 1274, 1522],
    protein: [69.28, 101.27, 101.11, 88.67, 56.16],
    carbs: [160.54, 57.97, 152.91, 129.55, 254.0],
    fat: [101.15, 153.12, 101.42, 135.67, 103.3],
    correlations: [
      [1.0, 0.16, 0.48],
      [0.16, 1.0, 0.27],
      [0.48, 0.27, 1.0]
    ],
    metrics: {
      avgProtein: 83.23,
      avgCarbs: 152.12,
      avgFat: 117.33,
      recordCount: 7806
    },
    metricLabels: ["Protein(g)", "Carbs(g)", "Fat(g)"],
    meta: {
      timestamp: new Date().toISOString(),
      executionTimeMs: 90,
      recordCount: 7806,
      sourceBlob: "Fallback sample"
    }
  };
}

function createFallbackRecipePayload() {
  return {
    items: [
      {
        id: 1,
        recipeName: "Mediterranean Chickpea Bowl",
        dietType: "mediterranean",
        summary: "Cuisine type: Mediterranean | Extraction day: Monday",
        nutrients: { "Protein(g)": 29, "Carbs(g)": 61, "Fat(g)": 18 },
        fields: {
          Recipe_name: "Mediterranean Chickpea Bowl",
          Diet_type: "mediterranean",
          Cuisine_type: "Mediterranean",
          "Protein(g)": 29,
          "Carbs(g)": 61,
          "Fat(g)": 18,
          Extraction_day: "Monday"
        }
      }
    ],
    filters: {
      dietType: recipeState.dietType,
      keyword: recipeState.keyword,
      availableDietTypes: ["dash", "keto", "mediterranean", "paleo", "vegan"],
      searchableColumns: ["Recipe_name", "Cuisine_type", "Extraction_day"]
    },
    pagination: {
      page: 1,
      pageSize: recipeState.pageSize,
      totalItems: 1,
      totalPages: 1,
      hasPreviousPage: false,
      hasNextPage: false,
      returnedCount: 1
    },
    meta: {
      sourceBlob: "Fallback sample",
      returnedCount: 1
    }
  };
}

function escapeHtml(value) {
  return String(value)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

function formatValue(value, suffix = "") {
  if (value == null || value === "") return "-";
  const numeric = Number(value);
  if (Number.isFinite(numeric)) {
    return `${numeric.toFixed(2).replace(/\.00$/, "")}${suffix}`;
  }
  return `${value}${suffix}`;
}

function showStatus(message, kind = "info") {
  if (!elements.status) return;

  elements.status.className = "fixed bottom-4 right-4 rounded-xl px-4 py-3 text-sm shadow-lg transition-opacity";
  const colors = {
    info: "bg-gray-900 text-white",
    success: "bg-green-600 text-white",
    error: "bg-red-600 text-white"
  };

  elements.status.classList.add(...colors[kind].split(" "));
  elements.status.textContent = message;
  elements.status.classList.remove("hidden");
  elements.status.style.opacity = "1";

  clearTimeout(elements.status._hideTimer);
  elements.status._hideTimer = setTimeout(() => {
    elements.status.style.opacity = "0";
  }, 2400);
}

function setAuthMessage(message, kind = "info") {
  if (!elements.authMessage) return;
  const styles = {
    info: "bg-blue-50 text-blue-800",
    success: "bg-green-50 text-green-800",
    error: "bg-red-50 text-red-800"
  };
  elements.authMessage.className = `mt-4 rounded-xl px-4 py-3 text-sm ${styles[kind]}`;
  elements.authMessage.textContent = message;
}

function saveToken(token) {
  authToken = token || "";
  if (authToken) {
    localStorage.setItem(TOKEN_KEY, authToken);
  } else {
    localStorage.removeItem(TOKEN_KEY);
  }
}

function setAuthenticatedView(user) {
  currentUser = user || null;

  elements.authSection?.classList.toggle("hidden", Boolean(user));
  elements.dashboardSection?.classList.toggle("hidden", !user);
  elements.userBar?.classList.toggle("hidden", !user);
  elements.userBar?.classList.toggle("flex", Boolean(user));

  if (elements.userName) {
    elements.userName.textContent = user ? `${user.displayName} (${user.provider})` : "";
  }

  if (!user) {
    setAuthMessage("Sign in to unlock the analytics dashboard.");
  }
}

function normalizeBackendPayload(data) {
  const dietRows = Array.isArray(data?.diets) ? data.diets : [];
  const proteinRows = Array.isArray(data?.protein) ? data.protein : [];
  const carbRows = Array.isArray(data?.carbs) ? data.carbs : [];
  const fatRows = Array.isArray(data?.fat) ? data.fat : [];

  const labels = proteinRows.length
    ? proteinRows.map(item => item["Diet_type"])
    : dietRows.map(item => item["Diet_type"]);

  const dietCountMap = new Map(dietRows.map(item => [item["Diet_type"], Number(item["Count"] ?? 0)]));
  const carbMap = new Map(carbRows.map(item => [item["Diet_type"], Number(item["Carbs(g)"] ?? 0)]));
  const fatMap = new Map(fatRows.map(item => [item["Diet_type"], Number(item["Fat(g)"] ?? 0)]));

  const protein = proteinRows.map(item => Number(item["Protein(g)"] ?? 0));
  const carbs = labels.map(label => carbMap.get(label) ?? 0);
  const fat = labels.map(label => fatMap.get(label) ?? 0);
  const dietCounts = labels.map(label => dietCountMap.get(label) ?? 0);

  const metricLabels = data?.correlations
    ? Object.keys(data.correlations)
    : ["Protein(g)", "Carbs(g)", "Fat(g)"];

  const correlations = metricLabels.map(rowKey =>
    metricLabels.map(colKey => Number(data?.correlations?.[rowKey]?.[colKey] ?? 0))
  );

  return {
    diets: labels,
    dietCounts,
    protein,
    carbs,
    fat,
    correlations,
    metrics: data?.metrics ?? {},
    metricLabels,
    meta: data?.meta
      ? {
          timestamp: data.meta.timestamp ?? data.meta.pipelineGeneratedAt ?? new Date().toISOString(),
          executionTimeMs: data.meta.executionTimeMs ?? data.meta.pipelineDurationMs ?? null,
          recordCount: data.meta.recordCount ?? labels.length,
          ...data.meta
        }
      : {
          timestamp: new Date().toISOString(),
          executionTimeMs: null,
          recordCount: labels.length
        }
  };
}

function normalizeRecipePayload(data) {
  return {
    items: Array.isArray(data?.items) ? data.items : [],
    filters: {
      dietType: data?.filters?.dietType ?? "all",
      keyword: data?.filters?.keyword ?? "",
      availableDietTypes: Array.isArray(data?.filters?.availableDietTypes) ? data.filters.availableDietTypes : [],
      searchableColumns: Array.isArray(data?.filters?.searchableColumns) ? data.filters.searchableColumns : []
    },
    pagination: {
      page: Number(data?.pagination?.page ?? 1),
      pageSize: Number(data?.pagination?.pageSize ?? recipeState.pageSize),
      totalItems: Number(data?.pagination?.totalItems ?? 0),
      totalPages: Number(data?.pagination?.totalPages ?? 1),
      hasPreviousPage: Boolean(data?.pagination?.hasPreviousPage),
      hasNextPage: Boolean(data?.pagination?.hasNextPage),
      returnedCount: Number(data?.pagination?.returnedCount ?? 0)
    },
    meta: data?.meta ?? {}
  };
}

async function apiFetch(path, options = {}) {
  const headers = {
    Accept: "application/json",
    ...(options.body ? { "Content-Type": "application/json" } : {}),
    ...(options.headers || {})
  };

  if (authToken) {
    headers.Authorization = `Bearer ${authToken}`;
  }

  const response = await fetch(apiUrl(path), { ...options, headers });

  let payload = {};
  const raw = await response.text();
  if (raw) {
    try {
      payload = JSON.parse(raw);
    } catch (error) {
      payload = { error: raw };
    }
  }

  if (!response.ok) {
    throw new Error(payload.error || `HTTP ${response.status}`);
  }

  return payload;
}

async function handleAuthSuccess(payload, successMessage) {
  saveToken(payload.token);
  currentUser = payload.user;
  setAuthenticatedView(currentUser);
  setAuthMessage(successMessage, "success");
  showStatus(successMessage, "success");
  await Promise.all([fetchInsights(), fetchRecipes()]);
}

async function verifyExistingSession() {
  if (!authToken) {
    setAuthenticatedView(null);
    return;
  }

  try {
    const payload = await apiFetch("/me");
    setAuthenticatedView(payload.user);
    await Promise.all([fetchInsights(), fetchRecipes()]);
  } catch (error) {
    saveToken("");
    setAuthenticatedView(null);
    setAuthMessage("Your session expired. Please sign in again.", "error");
  }
}

function renderSummaryCards(metrics = {}, meta = {}) {
  if (elements.avgProteinValue) elements.avgProteinValue.textContent = formatValue(metrics.avgProtein, " g");
  if (elements.avgCarbsValue) elements.avgCarbsValue.textContent = formatValue(metrics.avgCarbs, " g");
  if (elements.avgFatValue) elements.avgFatValue.textContent = formatValue(metrics.avgFat, " g");
  if (elements.recordCountValue) elements.recordCountValue.textContent = formatValue(meta.recordCount ?? metrics.recordCount);
}

function renderMeta({
  executionTimeMs,
  timestamp,
  recordCount,
  sourceBlob,
  cacheStatus,
  requestServedFromCache,
  requestExecutionTimeMs,
  sourceEtag
} = {}) {
  if (!elements.meta) return;

  elements.meta.innerHTML = `
    <p><span class="font-semibold">Last Run:</span> ${escapeHtml(timestamp ?? "-")}</p>
    <p><span class="font-semibold">Pipeline Time:</span> ${escapeHtml(formatValue(executionTimeMs, " ms"))}</p>
    <p><span class="font-semibold">Request Time:</span> ${escapeHtml(formatValue(requestExecutionTimeMs, " ms"))}</p>
    <p><span class="font-semibold">Records:</span> ${escapeHtml(formatValue(recordCount))}</p>
    <p><span class="font-semibold">Data Source:</span> ${escapeHtml(sourceBlob ?? "-")}</p>
    <p><span class="font-semibold">Cache:</span> ${escapeHtml(requestServedFromCache ? "hit" : (cacheStatus ?? "-"))}</p>
    <p><span class="font-semibold">Source ETag:</span> ${escapeHtml(sourceEtag ?? "-")}</p>
  `;
}

function buildOrUpdateBar(labels, protein) {
  const ctx = document.getElementById("barChart");
  const config = {
    type: "bar",
    data: {
      labels,
      datasets: [{
        label: "Protein (g)",
        data: protein,
        backgroundColor: "rgba(29, 78, 216, 0.72)",
        borderRadius: 8
      }]
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      animation: false,
      normalized: true,
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
    barChart = new Chart(ctx, config);
    return;
  }

  barChart.data.labels = labels;
  barChart.data.datasets[0].data = protein;
  barChart.update();
}

function buildOrUpdatePie(labels, values) {
  const ctx = document.getElementById("pieChart");
  const config = {
    type: "pie",
    data: {
      labels,
      datasets: [{
        data: values,
        backgroundColor: ["#1d4ed8", "#0f766e", "#ea580c", "#9333ea", "#d946ef", "#0891b2"]
      }]
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      animation: false,
      normalized: true,
      plugins: {
        title: { display: true, text: "Recipe Distribution by Diet Type" }
      }
    }
  };

  if (!pieChart) {
    pieChart = new Chart(ctx, config);
    return;
  }

  pieChart.data.labels = labels;
  pieChart.data.datasets[0].data = values;
  pieChart.update();
}

function buildOrUpdateScatter(carbs, protein, labels) {
  const ctx = document.getElementById("scatterPlot");
  const points = carbs.map((carbValue, index) => ({
    x: carbValue,
    y: protein[index],
    label: labels[index]
  }));

  const config = {
    type: "scatter",
    data: {
      datasets: [{
        label: "Protein vs Carbs",
        data: points,
        backgroundColor: "rgba(14, 165, 233, 0.8)"
      }]
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      animation: false,
      normalized: true,
      plugins: {
        title: { display: true, text: "Protein vs Carbohydrates" },
        tooltip: {
          callbacks: {
            label(context) {
              const point = context.raw;
              return `${point.label}: ${point.y}g protein, ${point.x}g carbs`;
            }
          }
        }
      },
      scales: {
        x: { title: { display: true, text: "Carbs (g)" } },
        y: { title: { display: true, text: "Protein (g)" } }
      }
    }
  };

  if (!scatterChart) {
    scatterChart = new Chart(ctx, config);
    return;
  }

  scatterChart.data.datasets[0].data = points;
  scatterChart.update();
}

function buildOrUpdateHeatmap(matrix, labels) {
  const container = document.getElementById("heatmap");
  if (!container) return;

  container.innerHTML = "";
  container.className = "mt-3 h-48 w-full overflow-auto";

  const size = labels.length;
  const grid = document.createElement("div");
  grid.style.display = "grid";
  grid.style.gridTemplateColumns = `max-content repeat(${size}, 1fr)`;
  grid.style.gap = "4px";
  grid.style.alignItems = "center";

  const colorFor = value => {
    const normalized = Math.max(-1, Math.min(1, Number(value)));
    if (normalized >= 0) {
      const tint = Math.round(255 - normalized * 110);
      return `rgb(${tint}, ${tint}, 255)`;
    }
    const tint = Math.round(255 - Math.abs(normalized) * 110);
    return `rgb(255, ${tint}, ${tint})`;
  };

  const emptyCorner = document.createElement("div");
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
      const value = Number(matrix[rowIndex]?.[colIndex] ?? 0);
      const cell = document.createElement("div");
      cell.title = `${labels[rowIndex]} vs ${labels[colIndex]}: ${value.toFixed(2)}`;
      cell.style.background = colorFor(value);
      cell.style.height = "28px";
      cell.style.borderRadius = "8px";
      cell.style.display = "flex";
      cell.style.alignItems = "center";
      cell.style.justifyContent = "center";
      cell.style.fontSize = "11px";
      cell.style.color = Math.abs(value) > 0.6 ? "#fff" : "#111";
      cell.textContent = value.toFixed(2);
      grid.appendChild(cell);
    }
  }

  container.appendChild(grid);
}

function renderAllFrom(data) {
  renderSummaryCards(data.metrics, data.meta);
  renderMeta(data.meta);

  if (chartsInitialized) {
    buildOrUpdateBar(data.diets, data.protein);
    buildOrUpdatePie(data.diets, data.dietCounts);
    buildOrUpdateScatter(data.carbs, data.protein, data.diets);
    buildOrUpdateHeatmap(data.correlations, data.metricLabels);
  }
}

function buildBrowseUrl() {
  const params = new URLSearchParams();
  params.set("page", String(recipeState.page));
  params.set("pageSize", String(recipeState.pageSize));

  if (recipeState.dietType && recipeState.dietType !== "all") {
    params.set("dietType", recipeState.dietType);
  }

  if (recipeState.keyword) {
    params.set("keyword", recipeState.keyword);
  }

  return `${apiUrl(RECIPES_API_PATH)}?${params.toString()}`;
}

function syncRecipeStateFromInputs() {
  recipeState.keyword = elements.keywordSearch?.value.trim() ?? "";
  recipeState.dietType = elements.dietTypeFilter?.value ?? "all";
  recipeState.pageSize = Number(elements.pageSizeSelect?.value ?? 10);
}

function populateDietFilter(options, selectedValue) {
  if (!elements.dietTypeFilter) return;

  const currentValue = selectedValue || elements.dietTypeFilter.value || "all";
  const dietOptions = ["all", ...options.filter(option => option && option.toLowerCase() !== "all")];

  elements.dietTypeFilter.innerHTML = dietOptions
    .map(option => {
      const label = option === "all" ? "All Diet Types" : option;
      const selected = option === currentValue ? "selected" : "";
      return `<option value="${escapeHtml(option)}" ${selected}>${escapeHtml(label)}</option>`;
    })
    .join("");
}

function updateQuickFilterButtons(activeDietType) {
  quickFilterButtons.forEach(button => {
    const isActive = (button.dataset.quickFilter || "all") === (activeDietType || "all");
    button.classList.toggle("active", isActive);
  });
}

function scrollToRecipeExplorer() {
  elements.recipeExplorerSection?.scrollIntoView({
    behavior: PREFERS_REDUCED_MOTION ? "auto" : "smooth",
    block: "start"
  });
}

function renderRecipeCards(items) {
  if (!elements.recipeResults) return;

  if (!items.length) {
    elements.recipeResults.innerHTML = `
      <article class="bg-white border border-dashed border-blue-200 rounded-2xl p-6 text-sm text-gray-500">
        No recipes matched the current search. Try another keyword or switch the diet filter back to All Diet Types.
      </article>
    `;
    return;
  }

  elements.recipeResults.innerHTML = items.map(item => {
    const nutrientEntries = Object.entries(item.nutrients || {});
    const fieldEntries = Object.entries(item.fields || {}).filter(([key]) => {
      return !["Recipe_name", "Recipe Name", "Diet_type", "Diet Type", "Protein(g)", "Carbs(g)", "Fat(g)"].includes(key);
    }).slice(0, 2);

    const nutrientMarkup = nutrientEntries.length
      ? `
        <div class="grid grid-cols-3 gap-2 mt-4">
          ${nutrientEntries.map(([label, value]) => `
            <div class="bg-blue-50 rounded-xl px-3 py-2 text-center">
              <p class="text-xs uppercase tracking-wide text-blue-700">${escapeHtml(label)}</p>
              <p class="font-semibold text-blue-900">${escapeHtml(formatValue(value, " g"))}</p>
            </div>
          `).join("")}
        </div>
      `
      : "";

    const fieldMarkup = fieldEntries.length
      ? `
        <div class="flex flex-wrap gap-2 mt-4">
          ${fieldEntries.map(([label, value]) => `
            <span class="text-xs bg-gray-100 text-gray-700 rounded-full px-3 py-1">
              ${escapeHtml(label.replace(/_/g, " "))}: ${escapeHtml(value)}
            </span>
          `).join("")}
        </div>
      `
      : "";

    return `
      <article class="bg-white rounded-2xl border border-blue-100 p-5 shadow-sm">
        <div class="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
          <div>
            <p class="text-xs uppercase tracking-wide text-blue-500">Recipe ${escapeHtml(item.id)}</p>
            <h3 class="text-xl font-semibold text-blue-950">${escapeHtml(item.recipeName || "Recipe")}</h3>
          </div>
          <span class="inline-flex items-center rounded-full bg-blue-100 text-blue-800 text-xs font-semibold px-3 py-1">
            ${escapeHtml(item.dietType || "Unknown")}
          </span>
        </div>
        <p class="text-sm text-gray-600 mt-3">${escapeHtml(item.summary || "No additional summary was returned for this recipe.")}</p>
        ${nutrientMarkup}
        ${fieldMarkup}
      </article>
    `;
  }).join("");
}

function createPaginationButtons(currentPage, totalPages) {
  const visibleButtons = [];
  const start = Math.max(1, currentPage - 2);
  const end = Math.min(totalPages, currentPage + 2);

  for (let pageNumber = start; pageNumber <= end; pageNumber += 1) {
    visibleButtons.push(pageNumber);
  }

  return visibleButtons;
}

function renderPaginationControls(pagination) {
  if (!elements.paginationControls) return;

  const buttons = createPaginationButtons(pagination.page, pagination.totalPages);

  elements.paginationControls.innerHTML = `
    <button
      class="px-4 py-2 rounded-xl border ${pagination.hasPreviousPage ? "bg-white text-blue-700 border-blue-200" : "bg-gray-100 text-gray-400 border-gray-200 cursor-not-allowed"}"
      data-page="${pagination.page - 1}"
      ${pagination.hasPreviousPage ? "" : "disabled"}
    >
      Previous
    </button>
    ${buttons.map(pageNumber => `
      <button
        class="px-4 py-2 rounded-xl border ${pageNumber === pagination.page ? "bg-blue-700 text-white border-blue-700" : "bg-white text-blue-700 border-blue-200"}"
        data-page="${pageNumber}"
      >
        ${pageNumber}
      </button>
    `).join("")}
    <button
      class="px-4 py-2 rounded-xl border ${pagination.hasNextPage ? "bg-white text-blue-700 border-blue-200" : "bg-gray-100 text-gray-400 border-gray-200 cursor-not-allowed"}"
      data-page="${pagination.page + 1}"
      ${pagination.hasNextPage ? "" : "disabled"}
    >
      Next
    </button>
  `;

  Array.from(elements.paginationControls.querySelectorAll("button[data-page]")).forEach(button => {
    button.addEventListener("click", () => {
      const nextPage = Number(button.dataset.page);
      if (!Number.isFinite(nextPage) || nextPage < 1 || nextPage === recipeState.page) return;
      recipeState.page = nextPage;
      fetchRecipes();
    });
  });
}

function renderRecipePayload(payload) {
  populateDietFilter(payload.filters.availableDietTypes, payload.filters.dietType);
  updateQuickFilterButtons(payload.filters.dietType || "all");
  renderRecipeCards(payload.items);
  renderPaginationControls(payload.pagination);

  const startRecord = payload.pagination.totalItems
    ? (payload.pagination.page - 1) * payload.pagination.pageSize + 1
    : 0;
  const endRecord = payload.pagination.totalItems
    ? startRecord + payload.items.length - 1
    : 0;

  if (elements.recipeSummary) {
    elements.recipeSummary.textContent = `Showing ${startRecord}-${endRecord} of ${payload.pagination.totalItems} recipes`;
  }

  if (elements.recipeMeta) {
    const searchColumns = payload.filters.searchableColumns.length
      ? payload.filters.searchableColumns.join(", ")
      : "dataset text columns";
    elements.recipeMeta.textContent = `Source: ${payload.meta.sourceBlob ?? "-"} | Search fields: ${searchColumns}`;
  }
}

async function fetchInsights() {
  if (!authToken) return;

  try {
    showStatus("Loading insights...", "info");
    const data = await apiFetch(INSIGHTS_API_PATH);
    lastDataset = normalizeBackendPayload(data);
    renderAllFrom(lastDataset);
    showStatus("Dashboard insights updated", "success");
  } catch (error) {
    console.error(error);
    if (!lastDataset) {
      lastDataset = createFallbackDataset();
      renderAllFrom(lastDataset);
    }
    showStatus(`Insight load failed: ${error.message}`, "error");
    if (error.message.toLowerCase().includes("auth")) {
      logout();
    }
  }
}

async function fetchRecipes() {
  if (!authToken) return;

  try {
    showStatus("Loading recipes...", "info");
    const response = await apiFetch(`${RECIPES_API_PATH}?${new URL(buildBrowseUrl()).searchParams.toString()}`);
    lastRecipePayload = normalizeRecipePayload(response);
    renderRecipePayload(lastRecipePayload);
    showStatus("Recipe browser updated", "success");
  } catch (error) {
    console.error(error);
    if (!lastRecipePayload) {
      lastRecipePayload = createFallbackRecipePayload();
      renderRecipePayload(lastRecipePayload);
    }
    if (elements.recipeMeta && lastRecipePayload?.meta?.sourceBlob === "Fallback sample") {
      elements.recipeMeta.textContent = "Showing fallback sample data until browseRecipes is deployed.";
    }
    showStatus(`Recipe load failed: ${error.message}`, "error");
    if (error.message.toLowerCase().includes("auth")) {
      logout();
    }
  }
}

function applyRecipeFilters(resetPage = true) {
  syncRecipeStateFromInputs();
  if (resetPage) {
    recipeState.page = 1;
  }
  updateQuickFilterButtons(recipeState.dietType);
  fetchRecipes();
}

function clearRecipeFilters() {
  recipeState.keyword = "";
  recipeState.dietType = "all";
  recipeState.page = 1;
  recipeState.pageSize = 10;

  if (elements.keywordSearch) elements.keywordSearch.value = "";
  if (elements.dietTypeFilter) elements.dietTypeFilter.value = "all";
  if (elements.pageSizeSelect) elements.pageSizeSelect.value = "10";

  updateQuickFilterButtons("all");
  fetchRecipes();
}

function applyQuickDietFilter(dietType) {
  recipeState.dietType = dietType || "all";
  recipeState.keyword = "";
  recipeState.page = 1;

  if (elements.keywordSearch) elements.keywordSearch.value = "";
  if (elements.dietTypeFilter) elements.dietTypeFilter.value = recipeState.dietType;

  updateQuickFilterButtons(recipeState.dietType);
  scrollToRecipeExplorer();
  fetchRecipes();
}

function showAllRecipes() {
  clearRecipeFilters();
  scrollToRecipeExplorer();
}

function renderChartsOnDemand() {
  if (chartsInitialized) {
    elements.chartsSection?.scrollIntoView({
      behavior: PREFERS_REDUCED_MOTION ? "auto" : "smooth",
      block: "start"
    });
    return;
  }

  chartsInitialized = true;
  elements.chartsPlaceholder?.classList.add("hidden");
  elements.chartsGrid?.classList.remove("hidden");
  elements.renderChartsBtn?.classList.add("hidden");

  if (lastDataset) {
    buildOrUpdateBar(lastDataset.diets, lastDataset.protein);
    buildOrUpdatePie(lastDataset.diets, lastDataset.dietCounts);
    buildOrUpdateScatter(lastDataset.carbs, lastDataset.protein, lastDataset.diets);
    buildOrUpdateHeatmap(lastDataset.correlations, lastDataset.metricLabels);
  }

  elements.chartsSection?.scrollIntoView({
    behavior: PREFERS_REDUCED_MOTION ? "auto" : "smooth",
    block: "start"
  });
}

function showLoginForm() {
  elements.loginForm?.classList.remove("hidden");
  elements.registerForm?.classList.add("hidden");
  elements.showLogin?.classList.add("bg-gray-900", "text-white");
  elements.showLogin?.classList.remove("text-gray-700");
  elements.showRegister?.classList.remove("bg-gray-900", "text-white");
  elements.showRegister?.classList.add("text-gray-700");
}

function showRegisterForm() {
  elements.registerForm?.classList.remove("hidden");
  elements.loginForm?.classList.add("hidden");
  elements.showRegister?.classList.add("bg-gray-900", "text-white");
  elements.showRegister?.classList.remove("text-gray-700");
  elements.showLogin?.classList.remove("bg-gray-900", "text-white");
  elements.showLogin?.classList.add("text-gray-700");
}

async function logout() {
  saveToken("");
  currentUser = null;
  setAuthenticatedView(null);
  showStatus("Logged out", "info");
}

async function startGithubLogin() {
  try {
    const payload = await apiFetch("/auth/github/start");
    sessionStorage.setItem(OAUTH_STATE_KEY, payload.state);
    window.location.href = payload.authUrl;
  } catch (error) {
    setAuthMessage(error.message, "error");
    showStatus(error.message, "error");
  }
}

function captureOAuthTokenFromUrl() {
  const url = new URL(window.location.href);
  const token = url.searchParams.get("token");
  const returnedState = url.searchParams.get("state");
  if (!token) return false;

  const expectedState = sessionStorage.getItem(OAUTH_STATE_KEY);
  if (!expectedState || returnedState !== expectedState) {
    saveToken("");
    setAuthMessage("OAuth verification failed. Please try GitHub login again.", "error");
    url.searchParams.delete("token");
    url.searchParams.delete("state");
    window.history.replaceState({}, "", url.toString());
    return false;
  }

  saveToken(token);
  sessionStorage.removeItem(OAUTH_STATE_KEY);
  url.searchParams.delete("token");
  url.searchParams.delete("state");
  window.history.replaceState({}, "", url.toString());
  setAuthMessage("GitHub sign-in complete. Loading your dashboard...", "success");
  return true;
}

elements.showLogin?.addEventListener("click", showLoginForm);
elements.showRegister?.addEventListener("click", showRegisterForm);
elements.logoutBtn?.addEventListener("click", logout);
elements.refreshData?.addEventListener("click", fetchInsights);
elements.githubLoginBtn?.addEventListener("click", startGithubLogin);
elements.searchRecipes?.addEventListener("click", () => applyRecipeFilters(true));
elements.clearFilters?.addEventListener("click", clearRecipeFilters);
elements.showAllRecipesBtn?.addEventListener("click", showAllRecipes);
elements.refreshRecipesBtn?.addEventListener("click", () => {
  scrollToRecipeExplorer();
  fetchRecipes();
});
elements.showChartsBtn?.addEventListener("click", renderChartsOnDemand);
elements.renderChartsBtn?.addEventListener("click", renderChartsOnDemand);
elements.pageSizeSelect?.addEventListener("change", () => applyRecipeFilters(true));
elements.dietTypeFilter?.addEventListener("change", () => applyRecipeFilters(true));
quickFilterButtons.forEach(button => {
  button.addEventListener("click", () => {
    applyQuickDietFilter(button.dataset.quickFilter || "all");
  });
});
elements.keywordSearch?.addEventListener("keydown", event => {
  if (event.key === "Enter") {
    event.preventDefault();
    applyRecipeFilters(true);
  }
});

elements.loginForm?.addEventListener("submit", async event => {
  event.preventDefault();
  const form = new FormData(event.currentTarget);

  try {
    const payload = await apiFetch("/login", {
      method: "POST",
      body: JSON.stringify({
        email: form.get("email"),
        password: form.get("password")
      })
    });
    await handleAuthSuccess(payload, "Logged in successfully.");
    event.currentTarget.reset();
  } catch (error) {
    setAuthMessage(error.message, "error");
    showStatus(error.message, "error");
  }
});

elements.registerForm?.addEventListener("submit", async event => {
  event.preventDefault();
  const form = new FormData(event.currentTarget);

  try {
    const payload = await apiFetch("/register", {
      method: "POST",
      body: JSON.stringify({
        displayName: form.get("displayName"),
        email: form.get("email"),
        password: form.get("password")
      })
    });
    await handleAuthSuccess(payload, "Account created successfully.");
    event.currentTarget.reset();
  } catch (error) {
    setAuthMessage(error.message, "error");
    showStatus(error.message, "error");
  }
});

showLoginForm();
captureOAuthTokenFromUrl();
verifyExistingSession();
