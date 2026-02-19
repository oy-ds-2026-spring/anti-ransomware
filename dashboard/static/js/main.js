// entropy line graph
const chartDom = document.getElementById("entropyChart");
const entropyChart = echarts.init(chartDom);
const chartOption = {
  backgroundColor: "transparent",
  tooltip: { trigger: "axis" },
  grid: { left: "2%", right: "5%", bottom: "5%", top: "10%", containLabel: true },
  xAxis: {
    type: "category",
    boundaryGap: false,
    data: [],
    axisLine: { lineStyle: { color: "#444" } },
    axisLabel: { color: "#aaa" },
  },
  yAxis: {
    type: "value",
    min: 0,
    max: 8,
    splitLine: { lineStyle: { color: "rgba(255, 255, 255, 0.1)" } },
    axisLabel: { color: "#aaa" },
  },
  series: [
    {
      name: "System Entropy",
      type: "line",
      smooth: true,
      symbol: "none",
      lineStyle: { width: 2, color: "#00FF00" },
      areaStyle: {
        color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
          { offset: 0, color: "rgba(0, 255, 0, 0.3)" },
          { offset: 1, color: "rgba(0, 255, 0, 0.05)" },
        ]),
      },
      data: [],
    },
  ],
};
entropyChart.setOption(chartOption);

// topology
const topoDom = document.getElementById("topologyChart");
const topologyChart = echarts.init(topoDom);

const topoOption = {
  tooltip: {},
  animationDurationUpdate: 500,
  animationEasingUpdate: "quinticInOut",
  series: [
    {
      type: "graph",
      layout: "none",
      symbolSize: 60,
      roam: false,
      label: { show: true, position: "bottom", color: "#fff", fontSize: 14, fontWeight: "bold" },
      edgeSymbol: ["none", "arrow"],
      edgeSymbolSize: [4, 10],
      // nodes
      data: [
        { name: "Backup Storage", x: 0, y: 50, itemStyle: { color: "#10b981" } },
        { name: "Recovery", x: 250, y: 50, itemStyle: { color: "#8b5cf6" } },
        { name: "Finance 1", x: 600, y: 0, itemStyle: { color: "#00FF00" } },
        { name: "Finance 2", x: 600, y: 33, itemStyle: { color: "#00FF00" } },
        { name: "Finance 3", x: 600, y: 66, itemStyle: { color: "#00FF00" } },
        { name: "Finance 4", x: 600, y: 100, itemStyle: { color: "#00FF00" } },
        { name: "RabbitMQ", x: 950, y: 50, itemStyle: { color: "#e34ce9" }, symbolSize: 75 },
        { name: "Detection", x: 1200, y: 50, itemStyle: { color: "#3b82f6" } },
      ],
      links: [
        {
          source: "Backup Storage",
          target: "Recovery",
          label: { show: true, formatter: "Pull Data", color: "#10b981" },
          lineStyle: { color: "#10b981", width: 2, type: "solid" },
        },
        // Recovery -> Finance Nodes
        {
          source: "Recovery",
          target: "Finance 1",
          symbol: ["arrow", "arrow"],
          symbolSize: [10, 10],
          lineStyle: { color: "#8b5cf6", curveness: -0.2, type: "dashed", width: 2 },
        },
        {
          source: "Recovery",
          target: "Finance 2",
          symbol: ["arrow", "arrow"],
          lineStyle: { color: "#8b5cf6", curveness: -0.1, type: "dashed", width: 2 },
        },
        {
          source: "Recovery",
          target: "Finance 3",
          symbol: ["arrow", "arrow"],
          lineStyle: { color: "#8b5cf6", curveness: 0.1, type: "dashed", width: 2 },
        },
        {
          source: "Recovery",
          target: "Finance 4",
          symbol: ["arrow", "arrow"],
          lineStyle: { color: "#8b5cf6", curveness: 0.2, type: "dashed", width: 2 },
        },

        // Finance Nodes -> RabbitMQ
        { source: "Finance 1", target: "RabbitMQ", lineStyle: { color: "#aaa", curveness: -0.2 } },
        { source: "Finance 2", target: "RabbitMQ", lineStyle: { color: "#aaa", curveness: -0.1 } },
        { source: "Finance 3", target: "RabbitMQ", lineStyle: { color: "#aaa", curveness: 0.1 } },
        { source: "Finance 4", target: "RabbitMQ", lineStyle: { color: "#aaa", curveness: 0.2 } },

        { source: "RabbitMQ", target: "Detection", lineStyle: { color: "#e34ce9", width: 2 } },

        // Detection -> Finance Nodes
        {
          source: "Detection",
          target: "Finance 1",
          lineStyle: { color: "#3b82f6", width: 2, curveness: 0.4, type: "dashed" },
        },
        {
          source: "Detection",
          target: "Finance 2",
          lineStyle: { color: "#3b82f6", width: 2, curveness: 0.3, type: "dashed" },
        },
        {
          source: "Detection",
          target: "Finance 3",
          lineStyle: { color: "#3b82f6", width: 2, curveness: -0.3, type: "dashed" },
        },
        {
          source: "Detection",
          target: "Finance 4",
          lineStyle: { color: "#3b82f6", width: 2, curveness: -0.4, type: "dashed" },
        },
      ],
      lineStyle: { opacity: 0.9, width: 2, curveness: 0 },
    },
  ],
};
topologyChart.setOption(topoOption);

window.addEventListener("resize", function () {
  entropyChart.resize();
  topologyChart.resize();
});

// button attack/normal
async function triggerAction(target, action) {
  try {
    // POST request
    await fetch(`/api/action/${target}/${action}`, { method: "POST" });
    console.log(`Command [${action}] sent to [${target}]`);
  } catch (error) {
    console.error("Action failed:", error);
  }
}

// data refresh
function formatLog(logStr) {
  let colorClass = "log-yellow";
  if (logStr.includes("MALWARE") || logStr.includes("🔴")) colorClass = "log-red";
  if (logStr.includes("RESTORED") || logStr.includes("✅") || logStr.includes("Safe")) colorClass = "log-green";
  return `<div class="log-entry ${colorClass}">${logStr}</div>`;
}

async function fetchState() {
  try {
    const response = await fetch("/api/state");
    const state = await response.json();

    // status for Finance 1-4
    for (let i = 1; i <= 4; i++) {
      const el = document.getElementById(`finance${i}-status`);
      if (el) {
        const val = state[`finance${i}`] || "Safe";
        el.innerText = val;
        if (val === "Infected") el.className = "value status-danger";
        else if (val === "Locked") el.className = "value status-warning";
        else el.className = "value status-safe";
      }
    }

    const currentEntropy = state.last_entropy || 0.0;
    const entEl = document.getElementById("entropy-value");
    entEl.innerText = currentEntropy.toFixed(2);
    entEl.className = currentEntropy > 7.5 ? "value status-danger" : "value status-safe";

    // line graph
    if (state.entropy_history && state.entropy_history.length > 0) {
      const times = state.entropy_history.map((d) => d.Time);
      const entropies = state.entropy_history.map((d) => d.Entropy);
      const isCritical = currentEntropy > 7.5;
      entropyChart.setOption({
        xAxis: { data: times },
        series: [
          {
            data: entropies,
            lineStyle: { color: isCritical ? "#FF4B4B" : "#00FF00" },
            areaStyle: {
              color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
                { offset: 0, color: isCritical ? "rgba(255, 75, 75, 0.3)" : "rgba(0, 255, 0, 0.3)" },
                { offset: 1, color: isCritical ? "rgba(255, 75, 75, 0.05)" : "rgba(0, 255, 0, 0.05)" },
              ]),
            },
          },
        ],
      });
    }

    // topology node color
    const getColor = (status) => {
      if (status === "Infected") return "#FF4B4B";
      if (status === "Locked") return "#FFA500";
      return "#00FF00";
    };

    topologyChart.setOption({
      series: [
        {
          data: [
            { name: "Backup Storage", x: 0, y: 50, itemStyle: { color: "#10b981" } },
            { name: "Recovery", x: 250, y: 50, itemStyle: { color: "#8b5cf6" } },
            { name: "Finance 1", x: 600, y: 0, itemStyle: { color: getColor(state.finance1) } },
            { name: "Finance 2", x: 600, y: 33, itemStyle: { color: getColor(state.finance2) } },
            { name: "Finance 3", x: 600, y: 66, itemStyle: { color: getColor(state.finance3) } },
            { name: "Finance 4", x: 600, y: 100, itemStyle: { color: getColor(state.finance4) } },
            { name: "RabbitMQ", x: 950, y: 50, itemStyle: { color: "#e34ce9" }, symbolSize: 75 },
            { name: "Detection", x: 1200, y: 50, itemStyle: { color: "#3b82f6" } },
          ],
        },
      ],
    });

    // log
    const eventLogDiv = document.getElementById("event-logs");
    if (state.logs && Array.isArray(state.logs)) {
      eventLogDiv.innerHTML = [...state.logs].reverse().map(formatLog).join("");
    }
    const procLogDiv = document.getElementById("processing-logs");
    if (state.processing_logs && Array.isArray(state.processing_logs)) {
      procLogDiv.innerHTML = [...state.processing_logs].reverse().map(formatLog).join("");
    }
  } catch (error) {
    console.error("Failed to fetch state:", error);
  }
}

setInterval(fetchState, 1000);
fetchState();
