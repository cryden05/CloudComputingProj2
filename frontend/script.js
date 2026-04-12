const API_BASE_URL = "http://localhost:7071/api";
const TOKEN_KEY = "nutrition_dashboard_token";
const OAUTH_STATE_KEY = "nutrition_dashboard_oauth_state";

let authToken = localStorage.getItem(TOKEN_KEY) || "";
let currentUser = null;
let lastDataset = null;
let barChart;
let pieChart;
let scatterChart;

function apiUrl(path) {
  return `${API_BASE_URL}${path}`;
}

function showStatus(msg, kind = "info") {
  const el = document.getElementById("status");
  if (!el) return;

  el.className = "fixed bottom-4 right-4 rounded-xl px-4 py-3 text-sm shadow-lg transition-opacity";
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

function setAuthMessage(message, kind = "info") {
  const el = document.getElementById("authMessage");
  if (!el) return;

  const styles = {
    info: "bg-blue-50 text-blue-800",
    success: "bg-green-50 text-green-800",
    error: "bg-red-50 text-red-800"
  };

  el.className = `mt-4 rounded-xl px-4 py-3 text-sm ${styles[kind]}`;
  el.textContent = message;
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

  document.getElementById("authSection")?.classList.toggle("hidden", Boolean(user));
  document.getElementById("dashboardSection")?.classList.toggle("hidden", !user);
  document.getElementById("userBar")?.classList.toggle("hidden", !user);
  document.getElementById("userBar")?.classList.toggle("flex", Boolean(user));

  const userNameEl = document.getElementById("userName");
  if (userNameEl) {
    userNameEl.textContent = user ? `${user.displayName} (${user.provider})` : "";
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

  const diets = proteinRows.length
    ? proteinRows.map((item) => item["Diet_type"])
    : dietRows.map((item) => item["Diet_type"]);
  const protein = proteinRows.map((item) => Number(item["Protein(g)"] ?? 0));
  const carbs = carbRows.map((item) => Number(item["Carbs(g)"] ?? 0));
  const fat = fatRows.map((item) => Number(item["Fat(g)"] ?? 0));

  const metrics = data?.correlations
    ? Object.keys(data.correlations)
    : ["Protein(g)", "Carbs(g)", "Fat(g)"];

  const correlations = metrics.map((rowKey) =>
    metrics.map((colKey) => Number(data?.correlations?.[rowKey]?.[colKey] ?? 0))
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

async function apiFetch(path, options = {}) {
  const headers = {
    Accept: "application/json",
    ...(options.body ? { "Content-Type": "application/json" } : {}),
    ...(options.headers || {})
  };

  if (authToken) {
    headers.Authorization = `Bearer ${authToken}`;
  }

  const response = await fetch(apiUrl(path), {
    ...options,
    headers
  });

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
  await fetchInsights();
}

async function verifyExistingSession() {
  if (!authToken) {
    setAuthenticatedView(null);
    return;
  }

  try {
    const payload = await apiFetch("/me");
    setAuthenticatedView(payload.user);
    await fetchInsights();
  } catch (error) {
    saveToken("");
    setAuthenticatedView(null);
    setAuthMessage("Your session expired. Please sign in again.", "error");
  }
}

async function fetchInsights() {
  if (!authToken) return;

  try {
    showStatus("Loading dashboard...", "info");
    const data = await apiFetch("/getDietData");
    lastDataset = normalizeBackendPayload(data);
    renderAllFrom(lastDataset);
    showStatus("Dashboard updated", "success");
  } catch (error) {
    console.error(error);
    showStatus(error.message, "error");
    if (error.message.toLowerCase().includes("auth")) {
      logout();
    }
  }
}

function renderMeta({ executionTimeMs, timestamp, recordCount } = {}) {
  const el = document.getElementById("meta");
  if (!el) return;
  el.innerHTML = `
    <p><span class="font-semibold">Last Run:</span> ${timestamp ?? "-"}</p>
    <p><span class="font-semibold">Execution Time:</span> ${executionTimeMs != null ? `${executionTimeMs} ms` : "-"}</p>
    <p><span class="font-semibold">Records:</span> ${recordCount ?? "-"}</p>
  `;
}

function buildOrUpdateBar(labels, protein) {
  const ctx = document.getElementById("barChart");
  const cfg = {
    type: "bar",
    data: {
      labels,
      datasets: [{
        label: "Protein (g)",
        data: protein,
        backgroundColor: "rgba(16, 185, 129, 0.72)"
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
        backgroundColor: ["#16a34a", "#0284c7", "#f97316", "#e11d48", "#7c3aed"]
      }]
    },
    options: {
      responsive: true,
      plugins: { title: { display: true, text: "Average Carbohydrates by Diet Type" } }
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
        backgroundColor: "rgba(37, 99, 235, 0.85)"
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
  container.className = "mt-3 h-48 w-full overflow-auto";

  const size = labels.length;
  const grid = document.createElement("div");
  grid.style.display = "grid";
  grid.style.gridTemplateColumns = `max-content repeat(${size}, 1fr)`;
  grid.style.gap = "4px";
  grid.style.alignItems = "center";

  const colorFor = (value) => {
    const clamped = Math.max(0, Math.min(1, value));
    const r = Math.round(240 - clamped * 140);
    const g = Math.round(250 - clamped * 50);
    const b = Math.round(255 - clamped * 210);
    return `rgb(${r},${g},${b})`;
  };

  const emptyCorner = document.createElement("div");
  emptyCorner.style.padding = "4px 8px";
  grid.appendChild(emptyCorner);

  labels.forEach((label) => {
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
      cell.style.borderRadius = "8px";
      cell.style.display = "flex";
      cell.style.alignItems = "center";
      cell.style.justifyContent = "center";
      cell.style.fontSize = "11px";
      cell.style.color = value > 0.55 ? "#fff" : "#111";
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

function showLoginForm() {
  document.getElementById("loginForm")?.classList.remove("hidden");
  document.getElementById("registerForm")?.classList.add("hidden");
  document.getElementById("showLogin")?.classList.add("bg-gray-900", "text-white");
  document.getElementById("showLogin")?.classList.remove("text-gray-700");
  document.getElementById("showRegister")?.classList.remove("bg-gray-900", "text-white");
  document.getElementById("showRegister")?.classList.add("text-gray-700");
}

function showRegisterForm() {
  document.getElementById("registerForm")?.classList.remove("hidden");
  document.getElementById("loginForm")?.classList.add("hidden");
  document.getElementById("showRegister")?.classList.add("bg-gray-900", "text-white");
  document.getElementById("showRegister")?.classList.remove("text-gray-700");
  document.getElementById("showLogin")?.classList.remove("bg-gray-900", "text-white");
  document.getElementById("showLogin")?.classList.add("text-gray-700");
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

document.getElementById("showLogin")?.addEventListener("click", showLoginForm);
document.getElementById("showRegister")?.addEventListener("click", showRegisterForm);
document.getElementById("logoutBtn")?.addEventListener("click", logout);
document.getElementById("refreshData")?.addEventListener("click", fetchInsights);
document.getElementById("githubLoginBtn")?.addEventListener("click", startGithubLogin);

document.getElementById("loginForm")?.addEventListener("submit", async (event) => {
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

document.getElementById("registerForm")?.addEventListener("submit", async (event) => {
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
