// frontend/src/App.jsx
import { useMemo, useRef, useState } from "react";
import "./App.css";
import BlockNode from "./components/Node/BlockNode.jsx";

// ---- Block catalog (frontend-only) ----
const DEFAULT_MODEL_PATH =
  "D:/Work/robot-blocks/backend/.venv/Lib/site-packages/mujoco/testdata/model.xml";

const BLOCK_CATALOG = {
  mujoco_sim: {
    label: "MuJoCo Sim",
    category: "sim",
    inputs: [{ name: "command", type: "cartesian_cmd" }],
    outputs: [{ name: "state", type: "robot_state" }],
    params: {
      model_path: DEFAULT_MODEL_PATH,  
      dof_index: 0,
      dx_scale: 1,
      apply_mode: "qpos",
      substeps_per_tick: 1,
      max_abs_x: 1000000000,
    },
  },
  cartesian_control: {
    label: "Cartesian Control",
    category: "control",
    inputs: [{ name: "state", type: "robot_state" }],
    outputs: [{ name: "command", type: "cartesian_cmd" }],
    params: {
      goal_x: 0.5,
      step: 0.005,
    },
  },
};

// small helper
const uid = () => Math.random().toString(16).slice(2, 8);

function deepClone(obj) {
  return JSON.parse(JSON.stringify(obj));
}

function getPortType(nodeType, portName, direction) {
  const spec = BLOCK_CATALOG[nodeType];
  if (!spec) return null;
  const list = direction === "input" ? spec.inputs : spec.outputs;
  const found = list.find((p) => p.name === portName);
  return found ? found.type : null;
}

function computeExecutionOrder(nodes) {
  // deterministic: sim blocks first, then everything else, stable by node label/id
  const sims = [];
  const rest = [];
  for (const n of nodes) {
    const cat = BLOCK_CATALOG[n.type]?.category || "other";
    if (cat === "sim") sims.push(n);
    else rest.push(n);
  }
  const byName = (a, b) => (a.label + a.id).localeCompare(b.label + b.id);
  sims.sort(byName);
  rest.sort(byName);
  return [...sims, ...rest].map((n) => n.id);
}

export default function App() {
  // ---- Initial nodes (you can delete these later) ----
  const [nodes, setNodes] = useState(() => {
    const simId = `mujoco_sim_${uid()}`;
    const ctrlId = `cartesian_control_${uid()}`;
    return [
      {
        id: simId,
        type: "mujoco_sim",
        label: BLOCK_CATALOG.mujoco_sim.label,
        x: 140,
        y: 140,
        params: deepClone(BLOCK_CATALOG.mujoco_sim.params),
      },
      {
        id: ctrlId,
        type: "cartesian_control",
        label: BLOCK_CATALOG.cartesian_control.label,
        x: 780,
        y: 140,
        params: deepClone(BLOCK_CATALOG.cartesian_control.params),
      },
    ];
  });

  const [edges, setEdges] = useState(() => {
    // default connect full loop if the two defaults exist
    // (safe; user can delete later)
    return [];
  });

  const [selectedNodeId, setSelectedNodeId] = useState(null);

  // Connection UX
  const [pendingFrom, setPendingFrom] = useState(null); // { nodeId, port, msgType }
  const [toast, setToast] = useState(null);

  // Run config UI
  const [runCfg, setRunCfg] = useState({
    duration_sec: 10,
    hz: 20,
    viewer: true,
    overrides: {},
  });

  // Backend run status
  const [runStatus, setRunStatus] = useState(null); // {loading, error, run_dir, metrics}

  const canvasRef = useRef(null);

  const selectedNode = useMemo(
    () => nodes.find((n) => n.id === selectedNodeId) || null,
    [nodes, selectedNodeId]
  );

  const canConnect = (from, to) => {
    if (!from || !to) return { ok: false, reason: "Missing endpoint" };
    if (from.nodeId === to.nodeId) return { ok: false, reason: "Same node" };

    const fromNode = nodes.find((n) => n.id === from.nodeId);
    const toNode = nodes.find((n) => n.id === to.nodeId);
    if (!fromNode || !toNode) return { ok: false, reason: "Node not found" };

    const outType = getPortType(fromNode.type, from.port, "output");
    const inType = getPortType(toNode.type, to.port, "input");
    if (!outType || !inType) return { ok: false, reason: "Port not found" };

    if (outType !== inType) {
      return { ok: false, reason: `Type mismatch: ${outType} → ${inType}` };
    }

    const fromKey = `${from.nodeId}.${from.port}`;
    const toKey = `${to.nodeId}.${to.port}`;
    const exists = edges.some((e) => e.from === fromKey && e.to === toKey);
    if (exists) return { ok: false, reason: "Edge already exists" };

    return { ok: true, msg_type: outType };
  };

  const showToast = (msg) => {
    setToast(msg);
    window.clearTimeout(showToast._t);
    showToast._t = window.setTimeout(() => setToast(null), 1800);
  };

  // ---- Graph builder (frontend → backend contract) ----
  const buildGraphV1 = () => {
    const execution_order = computeExecutionOrder(nodes);

    return {
      version: "graph.v1",
      execution_order,
      nodes: nodes.map((n) => ({
        id: n.id,
        type: n.type,
        label: n.label,
        params: n.params,
        ui: { x: n.x, y: n.y },
      })),
      edges: edges.map((e) => ({
        from: e.from,
        to: e.to,
        msg_type: e.msg_type,
      })),
      run_config: runCfg,
    };
  };

  const downloadGraph = () => {
    const g = buildGraphV1();
    const blob = new Blob([JSON.stringify(g, null, 2)], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = "graph.v1.json";
    a.click();
    URL.revokeObjectURL(url);
  };

  // ---- Minimal graph validation before RUN ----
  const validateForRun = () => {
    // must have at least 1 sim and 1 ctrl? not strictly, but useful
    const hasMuJoCo = nodes.some((n) => n.type === "mujoco_sim");
    if (!hasMuJoCo) return { ok: false, reason: "No MuJoCo sim node" };

    // If any mujoco sim has empty model_path -> fail
    for (const n of nodes) {
      if (n.type === "mujoco_sim") {
        const mp = (n.params?.model_path || "").trim();
        if (!mp) return { ok: false, reason: `Model path is empty on ${n.id}` };
      }
    }

    // Must have at least one edge
    if (edges.length === 0) return { ok: false, reason: "No connections (edges) yet" };

    return { ok: true };
  };

  // ---- Day 13: Run from UI (requires backend FastAPI server on :8000) ----
  const runFromUI = async ({ headless = true } = {}) => {
    const v = validateForRun();
    if (!v.ok) {
      showToast(`Cannot run: ${v.reason}`);
      return;
    }

    try {
      setRunStatus({ loading: true });
      const graph = buildGraphV1();

      const res = await fetch("http://localhost:8000/api/run", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ graph, headless }),
      });

      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || "Run failed");

      setRunStatus({
        loading: false,
        run_dir: data.run_dir,
        metrics: data.metrics,
      });

      showToast("Run finished ✅");
    } catch (e) {
      setRunStatus({ loading: false, error: String(e) });
      showToast(`Run failed: ${String(e)}`);
    }
  };

  // ---- Node ops ----
  const addNode = (type) => {
    const spec = BLOCK_CATALOG[type];
    if (!spec) return;

    const id = `${type}_${uid()}`;
    const newNode = {
      id,
      type,
      label: spec.label,
      x: 160 + Math.floor(Math.random() * 120),
      y: 260 + Math.floor(Math.random() * 140),
      params: deepClone(spec.params),
    };
    setNodes((prev) => [...prev, newNode]);
    setSelectedNodeId(id);
  };

  const removeSelectedNode = () => {
    if (!selectedNodeId) return;
    const id = selectedNodeId;
    setNodes((prev) => prev.filter((n) => n.id !== id));
    setEdges((prev) =>
      prev.filter((e) => !(e.from.startsWith(id + ".") || e.to.startsWith(id + ".")))
    );
    setSelectedNodeId(null);
    showToast("Node deleted");
  };

  const updateSelectedParam = (key, value) => {
    if (!selectedNodeId) return;
    setNodes((prev) =>
      prev.map((n) => {
        if (n.id !== selectedNodeId) return n;
        return {
          ...n,
          params: { ...(n.params || {}), [key]: value },
        };
      })
    );
  };

  // ---- Connection handlers ----
  const onOutputMouseDown = (nodeId, portName) => {
    const node = nodes.find((n) => n.id === nodeId);
    if (!node) return;
    const msgType = getPortType(node.type, portName, "output");
    if (!msgType) return;
    setPendingFrom({ nodeId, port: portName, msgType });
    showToast(`Select input for: ${portName} (${msgType})`);
  };

  const onInputMouseUp = (nodeId, portName) => {
    if (!pendingFrom) return;

    const to = { nodeId, port: portName };
    const check = canConnect(
      { nodeId: pendingFrom.nodeId, port: pendingFrom.port },
      to
    );

    if (!check.ok) {
      showToast(check.reason);
      setPendingFrom(null);
      return;
    }

    const fromKey = `${pendingFrom.nodeId}.${pendingFrom.port}`;
    const toKey = `${nodeId}.${portName}`;

    setEdges((prev) => [
      ...prev,
      {
        from: fromKey,
        to: toKey,
        msg_type: check.msg_type,
      },
    ]);

    setPendingFrom(null);
    showToast("Connected ✅");
  };

  const removeEdge = (idx) => {
    setEdges((prev) => prev.filter((_, i) => i !== idx));
  };

  // ---- Render ----
  const leftStyle = {
    width: 420,
    padding: 16,
    borderRight: "1px solid #e5e7eb",
    background: "#fafafa",
    height: "100vh",
    overflow: "auto",
  };

  const btn = {
    width: "100%",
    padding: "10px 12px",
    borderRadius: 12,
    border: "1px solid #e5e7eb",
    background: "white",
    cursor: "pointer",
    fontWeight: 800,
    marginTop: 8,
  };

  const smallBtn = {
    padding: "8px 10px",
    borderRadius: 10,
    border: "1px solid #e5e7eb",
    background: "white",
    cursor: "pointer",
    fontWeight: 800,
  };

  const badge = (text) => (
    <span
      style={{
        display: "inline-block",
        padding: "4px 8px",
        borderRadius: 999,
        border: "1px solid #e5e7eb",
        background: "white",
        fontSize: 12,
        fontWeight: 800,
        marginLeft: 8,
      }}
    >
      {text}
    </span>
  );

  return (
    <div style={{ display: "flex", fontFamily: "system-ui, Segoe UI, Arial" }}>
      {/* LEFT SIDEBAR */}
      <div style={leftStyle}>
        <div style={{ fontSize: 22, fontWeight: 900 }}>robot-blocks</div>
        <div style={{ fontSize: 13, opacity: 0.7, marginTop: 4 }}>
          Visual graph → plan → execute
        </div>

        {/* Add blocks */}
        <div style={{ marginTop: 16, fontWeight: 900 }}>Add Blocks</div>
        <div style={{ display: "flex", gap: 10, marginTop: 8, flexWrap: "wrap" }}>
          <button style={smallBtn} onClick={() => addNode("mujoco_sim")}>
            + MuJoCo Sim
          </button>
          <button style={smallBtn} onClick={() => addNode("cartesian_control")}>
            + Cartesian Control
          </button>
        </div>

        {/* Run config */}
        <div style={{ marginTop: 18, fontWeight: 900 }}>
          Run Config {runCfg.viewer ? badge("viewer: ON") : badge("viewer: OFF")}
        </div>

        <div style={{ marginTop: 10, display: "grid", gap: 10 }}>
          <label style={{ fontSize: 13, fontWeight: 800 }}>
            duration_sec
            <input
              value={runCfg.duration_sec}
              onChange={(e) =>
                setRunCfg((p) => ({ ...p, duration_sec: Number(e.target.value || 0) }))
              }
              type="number"
              min="1"
              style={{ width: "100%", marginTop: 6, padding: 8, borderRadius: 10 }}
            />
          </label>

          <label style={{ fontSize: 13, fontWeight: 800 }}>
            hz
            <input
              value={runCfg.hz}
              onChange={(e) => setRunCfg((p) => ({ ...p, hz: Number(e.target.value || 0) }))}
              type="number"
              min="1"
              style={{ width: "100%", marginTop: 6, padding: 8, borderRadius: 10 }}
            />
          </label>

          <label style={{ fontSize: 13, fontWeight: 800, display: "flex", gap: 10 }}>
            <input
              type="checkbox"
              checked={!!runCfg.viewer}
              onChange={(e) => setRunCfg((p) => ({ ...p, viewer: e.target.checked }))}
            />
            viewer
          </label>
        </div>

        {/* Run buttons */}
        <div style={{ marginTop: 16, fontWeight: 900 }}>Run</div>
        <button style={btn} onClick={() => runFromUI({ headless: true })}>
          Run ▶ (headless via API)
        </button>
        <button style={btn} onClick={() => runFromUI({ headless: false })}>
          Run ▶ (with viewer via API)
        </button>

        <div style={{ marginTop: 10, fontSize: 12, opacity: 0.7 }}>
          Requires backend server: <code>uvicorn app.http_server:app --reload --port 8000</code>
        </div>

        {/* Export */}
        <div style={{ marginTop: 16, fontWeight: 900 }}>Export</div>
        <button style={btn} onClick={downloadGraph}>
          Export graph.v1.json
        </button>

        {/* Selected */}
        <div style={{ marginTop: 18, fontWeight: 900 }}>Inspector</div>
        {!selectedNode ? (
          <div style={{ marginTop: 8, fontSize: 13, opacity: 0.7 }}>
            Click a node to edit params.
          </div>
        ) : (
          <div style={{ marginTop: 10 }}>
            <div style={{ fontSize: 16, fontWeight: 900 }}>{selectedNode.label}</div>
            <div style={{ fontSize: 12, opacity: 0.7, fontFamily: "monospace" }}>
              {selectedNode.id}
            </div>

            <div style={{ marginTop: 12, display: "grid", gap: 10 }}>
              {Object.entries(selectedNode.params || {}).map(([k, v]) => (
                <label key={k} style={{ fontSize: 13, fontWeight: 800 }}>
                  {k}
                  <input
                    value={String(v)}
                    onChange={(e) => {
                      const raw = e.target.value;
                      // try numeric cast for numeric fields
                      const num = Number(raw);
                      const next = raw.trim() !== "" && !Number.isNaN(num) ? num : raw;
                      updateSelectedParam(k, next);
                    }}
                    style={{ width: "100%", marginTop: 6, padding: 8, borderRadius: 10 }}
                  />
                </label>
              ))}
            </div>

            <button
              style={{ ...btn, border: "1px solid #fecaca", background: "#fff1f2" }}
              onClick={removeSelectedNode}
            >
              Delete node
            </button>
          </div>
        )}

        {/* Edges list */}
        <div style={{ marginTop: 18, fontWeight: 900 }}>
          Edges {badge(String(edges.length))}
        </div>
        <div style={{ marginTop: 10, display: "grid", gap: 10 }}>
          {edges.length === 0 ? (
            <div style={{ fontSize: 13, opacity: 0.7 }}>
              Drag from an <b>output</b> (green dot) to an <b>input</b> (blue dot).
            </div>
          ) : (
            edges.map((e, idx) => (
              <div
                key={idx}
                style={{
                  padding: 10,
                  borderRadius: 12,
                  border: "1px solid #e5e7eb",
                  background: "white",
                }}
              >
                <div style={{ fontSize: 12, fontFamily: "monospace" }}>
                  {e.from} → {e.to}
                </div>
                <div style={{ fontSize: 12, opacity: 0.7, marginTop: 4 }}>
                  {e.msg_type}
                </div>
                <button
                  onClick={() => removeEdge(idx)}
                  style={{
                    marginTop: 8,
                    padding: "6px 10px",
                    borderRadius: 10,
                    border: "1px solid #e5e7eb",
                    background: "#f8fafc",
                    cursor: "pointer",
                    fontWeight: 800,
                  }}
                >
                  Remove
                </button>
              </div>
            ))
          )}
        </div>

        {/* Run result */}
        <div style={{ marginTop: 18, fontWeight: 900 }}>Last Run</div>
        <div style={{ marginTop: 8, fontSize: 13 }}>
          {runStatus?.loading ? (
            <div>Running…</div>
          ) : runStatus?.error ? (
            <div style={{ color: "crimson", whiteSpace: "pre-wrap" }}>{runStatus.error}</div>
          ) : runStatus?.metrics ? (
            <div>
              <div style={{ fontSize: 12 }}>
                <b>run_dir:</b> <code>{runStatus.run_dir}</code>
              </div>
              <pre style={{ marginTop: 10, fontSize: 12, whiteSpace: "pre-wrap" }}>
                {JSON.stringify(runStatus.metrics, null, 2)}
              </pre>
            </div>
          ) : (
            <div style={{ opacity: 0.7 }}>No run yet.</div>
          )}
        </div>

        {/* Toast */}
        {toast ? (
          <div
            style={{
              position: "sticky",
              bottom: 12,
              marginTop: 18,
              padding: 10,
              borderRadius: 12,
              border: "1px solid #e5e7eb",
              background: "white",
              fontWeight: 900,
            }}
          >
            {toast}
          </div>
        ) : null}
      </div>

      {/* CANVAS */}
      <div
        ref={canvasRef}
        style={{
          flex: 1,
          height: "100vh",
          overflow: "auto",
          background:
            "radial-gradient(circle at 1px 1px, rgba(0,0,0,0.08) 1px, transparent 0)",
          backgroundSize: "18px 18px",
          position: "relative",
          padding: 40,
        }}
        onMouseDown={() => {
          // click empty canvas cancels pending connect
          if (pendingFrom) {
            setPendingFrom(null);
            showToast("Cancelled connection");
          }
          setSelectedNodeId(null);
        }}
      >
        <div style={{ display: "flex", gap: 28, flexWrap: "wrap" }}>
          {nodes.map((n) => {
            const spec = BLOCK_CATALOG[n.type];

            return (
              <div
                key={n.id}
                style={{ position: "absolute", left: n.x, top: n.y }}
                onMouseDown={(e) => {
                  e.stopPropagation();
                  setSelectedNodeId(n.id);
                }}
              >
                <BlockNode
                  title={n.label}
                  id={n.id}
                  inputs={(spec?.inputs || []).map((p) => ({ name: p.name, type: p.type }))}
                  outputs={(spec?.outputs || []).map((p) => ({ name: p.name, type: p.type }))}
                  onOutputMouseDown={(p) => onOutputMouseDown(n.id, p.name)}
                  onInputMouseUp={(p) => onInputMouseUp(n.id, p.name)}
                />
              </div>
            );
          })}
        </div>

        {/* Small hint when connecting */}
        {pendingFrom ? (
          <div
            style={{
              position: "fixed",
              right: 16,
              bottom: 16,
              padding: 12,
              borderRadius: 14,
              background: "white",
              border: "1px solid #e5e7eb",
              boxShadow: "0 10px 30px rgba(0,0,0,0.08)",
              fontWeight: 900,
            }}
          >
            Connecting from <code>{pendingFrom.nodeId + "." + pendingFrom.port}</code>
            <div style={{ fontSize: 12, opacity: 0.7, marginTop: 6 }}>
              Click an input (blue dot) to connect.
            </div>
          </div>
        ) : null}
      </div>
    </div>
  );
}
