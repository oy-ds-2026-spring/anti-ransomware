const COLORS = {
  SAFE: "#22dd11",
  INFECTED: "#f65e5e",
  LOCKED: "#f5bb4e",
  BACKUP: "#76bca5",
  RECOVERY: "#76bca5",
  GATEWAY: "#778beb",
  RABBITMQ: "#d081d3",
  DETECTION: "#3b82f6",
  AXIS_LINE: "#444",
  TEXT_WHITE: "#fff",
  SPLIT_LINE: "rgba(255, 255, 255, 0.03)",
  AREA_SAFE_START: "rgba(0, 255, 0, 0.3)",
  AREA_SAFE_END: "rgba(0, 255, 0, 0.03)",
  AREA_CRITICAL_START: "rgba(255, 75, 75, 0.3)",
  AREA_CRITICAL_END: "rgba(255, 75, 75, 0.03)",
};

let nodePositions = {};
let isDragging = false;

// entropy line graph
const chartDom = document.getElementById("entropyChart");
const entropyChart = echarts.init(chartDom, null, { renderer: "canvas", useDirtyRect: true });
const chartOption = {
  backgroundColor: "transparent",
  tooltip: { trigger: "axis" },
  grid: { left: "2%", right: "5%", bottom: "5%", top: "10%", containLabel: true },
  xAxis: {
    type: "category",
    boundaryGap: false,
    data: [],
    axisLine: { lineStyle: { color: COLORS.AXIS_LINE } },
    axisLabel: { color: COLORS.TEXT_WHITE },
  },
  yAxis: {
    type: "value",
    min: 0,
    max: 8,
    splitLine: { lineStyle: { color: COLORS.SPLIT_LINE } },
    axisLabel: { color: COLORS.TEXT_WHITE },
  },
  series: [
    {
      name: "System Entropy",
      type: "line",
      smooth: true,
      symbol: "none",
      lineStyle: { width: 2, color: COLORS.SAFE },
      areaStyle: {
        color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
          { offset: 0, color: COLORS.AREA_SAFE_START },
          { offset: 1, color: COLORS.AREA_SAFE_END },
        ]),
      },
      data: [],
    },
  ],
};
entropyChart.setOption(chartOption);

// topology
const topoDom = document.getElementById("topologyChart");
const topologyChart = echarts.init(topoDom, null, { renderer: "canvas", useDirtyRect: true });

const topoOption = {
  tooltip: {},
  animationDurationUpdate: 0,
  animation: false,
  series: [
    {
      type: "graph",
      layout: "none",
      draggable: true,
      symbolSize: 60,
      roam: false,
      label: { show: true, position: "bottom", color: COLORS.TEXT_WHITE, fontSize: 14, fontWeight: "bold" },
      edgeSymbol: ["none", "arrow"],
      edgeSymbolSize: [4, 10],
      // nodes
      data: [
        { name: "Backup Storage", x: 0, y: 50, itemStyle: { color: COLORS.BACKUP } },
        { name: "Recovery", x: 250, y: 50, itemStyle: { color: COLORS.RECOVERY } },
        { name: "Gateway", x: 450, y: 50, itemStyle: { color: COLORS.GATEWAY } },
        {
          name: "F1",
          x: 600,
          y: -100,
          symbolSize: 30,
          itemStyle: { color: COLORS.SAFE },
          label: { position: "inside", color: "black" },
        },
        {
          name: "F2",
          x: 600,
          y: 0,
          symbolSize: 30,
          itemStyle: { color: COLORS.SAFE },
          label: { position: "inside", color: "black" },
        },
        {
          name: "F3",
          x: 600,
          y: 100,
          symbolSize: 30,
          itemStyle: { color: COLORS.SAFE },
          label: { position: "inside", color: "black" },
        },
        {
          name: "F4",
          x: 600,
          y: 200,
          symbolSize: 30,
          itemStyle: { color: COLORS.SAFE },
          label: { position: "inside", color: "black" },
        },
        { name: "RabbitMQ", x: 950, y: 50, itemStyle: { color: COLORS.RABBITMQ } },
        { name: "Detection", x: 1200, y: 50, itemStyle: { color: COLORS.DETECTION } },
      ],
      links: [
        {
          source: "Backup Storage",
          target: "Recovery",
          label: { show: true, formatter: "Pull Data", color: COLORS.BACKUP },
          lineStyle: { color: COLORS.BACKUP, width: 2, type: "solid" },
        },
        // Recovery -> Finance Nodes
        {
          source: "Recovery",
          target: "F1",
          symbol: ["arrow", "arrow"],
          symbolSize: [10, 10],
          lineStyle: { color: COLORS.RECOVERY, curveness: -0.03, type: "dashed", width: 2 },
        },
        {
          source: "Recovery",
          target: "F2",
          symbol: ["arrow", "arrow"],
          symbolSize: [10, 10],
          lineStyle: { color: COLORS.RECOVERY, curveness: -0.03, type: "dashed", width: 2 },
        },
        {
          source: "Recovery",
          target: "F3",
          symbol: ["arrow", "arrow"],
          symbolSize: [10, 10],
          lineStyle: { color: COLORS.RECOVERY, curveness: 0.03, type: "dashed", width: 2 },
        },
        {
          source: "Recovery",
          target: "F4",
          symbol: ["arrow", "arrow"],
          symbolSize: [10, 10],
          lineStyle: { color: COLORS.RECOVERY, curveness: 0.03, type: "dashed", width: 2 },
        },

        // Gateway -> Finance Nodes
        {
          source: "Gateway",
          target: "F1",
          symbol: ["none", "arrow"],
          lineStyle: { color: COLORS.GATEWAY, width: 2, type: "solid" },
        },
        {
          source: "Gateway",
          target: "F2",
          symbol: ["none", "arrow"],
          lineStyle: { color: COLORS.GATEWAY, width: 2, type: "dashed" },
        },
        {
          source: "Gateway",
          target: "F3",
          symbol: ["none", "arrow"],
          lineStyle: { color: COLORS.GATEWAY, width: 2, type: "dashed" },
        },
        {
          source: "Gateway",
          target: "F4",
          symbol: ["none", "arrow"],
          lineStyle: { color: COLORS.GATEWAY, width: 2, type: "dashed" },
        },

        // Finance Nodes -> RabbitMQ
        {
          source: "F1",
          target: "RabbitMQ",
          symbol: ["arrow", "arrow"],
          symbolSize: [10, 10],
          lineStyle: { color: COLORS.RABBITMQ, curveness: -0.03 },
        },
        {
          source: "F2",
          target: "RabbitMQ",
          symbol: ["arrow", "arrow"],
          symbolSize: [10, 10],
          lineStyle: { color: COLORS.RABBITMQ, curveness: -0.03 },
        },
        {
          source: "F3",
          target: "RabbitMQ",
          symbol: ["arrow", "arrow"],
          symbolSize: [10, 10],
          lineStyle: { color: COLORS.RABBITMQ, curveness: 0.03 },
        },
        {
          source: "F4",
          target: "RabbitMQ",
          symbol: ["arrow", "arrow"],
          symbolSize: [10, 10],
          lineStyle: { color: COLORS.RABBITMQ, curveness: 0.03 },
        },

        {
          source: "RabbitMQ",
          target: "Detection",
          symbol: ["arrow", "arrow"],
          symbolSize: [10, 10],
          lineStyle: { color: COLORS.RABBITMQ, width: 2 },
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
  updateGraphics();
});

topologyChart.on("mousedown", function () {
  isDragging = true;
});

// Update graphics when drag ends
topologyChart.on("mouseup", function () {
  const model = topologyChart.getModel();
  const series = model.getSeriesByIndex(0);
  const data = series.getData();
  data.each(function (idx) {
    const name = data.getName(idx);
    const layout = data.getItemLayout(idx);
    if (layout) {
      nodePositions[name] = { x: layout[0], y: layout[1] };
    }
  });

  // Save positions to server
  fetch("/dashboard/positions", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(nodePositions),
  }).catch((e) => console.error("Failed to save positions:", e));

  isDragging = false;
  updateGraphics();
  fetchState();
});

// Update graphic elements (buttons) based on chart coordinates
function updateGraphics() {
  const graphics = [];

  const currentOption = topologyChart.getOption();
  const nodes = currentOption && currentOption.series && currentOption.series[0] ? currentOption.series[0].data : [];

  nodes.forEach((node) => {
    // Only for Gateway
    if (node.name === "Gateway") {
      let x = node.x;
      let y = node.y;
      if (nodePositions[node.name]) {
        x = nodePositions[node.name].x;
        y = nodePositions[node.name].y;
      }

      // Attack Button: x, y + 40
      const attackPos = topologyChart.convertToPixel({ seriesIndex: 0 }, [x, y + 70]);
      if (attackPos) {
        graphics.push({
          type: "group",
          position: attackPos,
          children: [
            {
              type: "rect",
              shape: { x: -30, y: -12.5, width: 60, height: 25 },
              style: { fill: COLORS.INFECTED },
            },
            {
              type: "text",
              style: {
                text: "Attack",
                fill: "#730000",
                font: "bold 12px sans-serif",
                textAlign: "center",
                textVerticalAlign: "middle",
              },
              position: [0, 0],
            },
          ],
          // Trigger attack via gateway
          onclick: () => triggerAttack(),
        });
      }
    }
  });

  topologyChart.setOption({ graphic: graphics });
}

// button attack
async function triggerAttack() {
  try {
    // GET request
    await fetch(`/dashboard/attack`, { method: "GET" });
    console.log(`Command [attack] sent to [GATEWAY]`);
  } catch (error) {
    console.error("Attack failed:", error);
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
  if (isDragging) return;

  try {
    const response = await fetch("/dashboard/state");
    const state = await response.json();

    // Double check: if dragging started during fetch, abort update to avoid resetting positions
    if (isDragging) return;

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
            lineStyle: { color: isCritical ? COLORS.INFECTED : COLORS.SAFE },
            areaStyle: {
              color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
                { offset: 0, color: isCritical ? COLORS.AREA_CRITICAL_START : COLORS.AREA_SAFE_START },
                { offset: 1, color: isCritical ? COLORS.AREA_CRITICAL_END : COLORS.AREA_SAFE_END },
              ]),
            },
          },
        ],
      });
    }

    // topology node color
    const getColor = (status) => {
      if (status === "Infected") return COLORS.INFECTED;
      if (status === "Locked") return COLORS.LOCKED;
      return COLORS.SAFE;
    };

    // Preserve node positions
    const getPos = (name, defX, defY) => {
      if (nodePositions[name]) return nodePositions[name];
      return { x: defX, y: defY };
    };

    topologyChart.setOption({
      series: [
        {
          data: [
            { name: "Backup Storage", ...getPos("Backup Storage", 0, 50), itemStyle: { color: COLORS.BACKUP } },
            { name: "Recovery", ...getPos("Recovery", 250, 50), itemStyle: { color: COLORS.RECOVERY } },
            { name: "Gateway", ...getPos("Gateway", 450, 50), itemStyle: { color: COLORS.GATEWAY } },
            {
              name: "F1",
              ...getPos("F1", 600, -100),
              symbolSize: 30,
              itemStyle: { color: getColor(state.finance1) },
              label: { position: "inside", color: "black" },
            },
            {
              name: "F2",
              ...getPos("F2", 600, 0),
              symbolSize: 30,
              itemStyle: { color: getColor(state.finance2) },
              label: { position: "inside", color: "black" },
            },
            {
              name: "F3",
              ...getPos("F3", 600, 100),
              symbolSize: 30,
              itemStyle: { color: getColor(state.finance3) },
              label: { position: "inside", color: "black" },
            },
            {
              name: "F4",
              ...getPos("F4", 600, 200),
              symbolSize: 30,
              itemStyle: { color: getColor(state.finance4) },
              label: { position: "inside", color: "black" },
            },
            { name: "RabbitMQ", ...getPos("RabbitMQ", 950, 50), itemStyle: { color: COLORS.RABBITMQ } },
            { name: "Detection", ...getPos("Detection", 1200, 50), itemStyle: { color: COLORS.DETECTION } },
          ],
        },
      ],
    });
    updateGraphics();

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

async function init() {
  try {
    const res = await fetch("/dashboard/positions");
    if (res.ok) {
      const data = await res.json();
      if (data) nodePositions = data;
    }
  } catch (e) {
    console.error("Failed to load positions:", e);
  }
  fetchState();
  setInterval(fetchState, 1000);
}

init();
