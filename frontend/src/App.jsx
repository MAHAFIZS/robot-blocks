// frontend/src/App.jsx
import { useEffect, useMemo, useRef, useState } from "react";
import "./App.css";
import BlockNode from "./components/Node/BlockNode.jsx";

// ----------------------------
// Block catalog (frontend-only)
// ----------------------------
const BLOCK_CATALOG = {
  constant_cmd: {
    label: "Constant Cmd",
    category: "input",
    inputs: [],
    outputs: [{ name: "command", type: "cartesian_cmd" }],
    params: {
      dx: 0.0,
      dy: 0.0,
      dz: 0.0,
      drx: 0.0,
      dry: 0.0,
      drz: 0.0,
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

  mujoco_sim: {
    label: "MuJoCo Sim",
    category: "sim",
    inputs: [{ name: "command", type: "cartesian_cmd" }],
    outputs: [{ name: "state", type: "robot_state" }],
    params: {
      model_path: "", // must be set in Inspector
      dof_index: 0,
      dx_scale: 1,
      apply_mode: "qpos",
      substeps_per_tick: 1,
      max_abs_x: 1000000000,
    },
  },

  logger: {
    label: "Logger",
    category: "sink",
    inputs: [{ name: "state", type: "robot_state" }],
    outputs: [],
    params: {
      tag: "run",
      every_n: 1,
    },
  },
};

// ----------------------------
// Helpers
// ----------------------------
const uid = () => Math.random().toString(16).slice(2, 8);
const deepClone = (obj) => JSON.parse(JSON.stringify(obj));

const STORAGE_KEY = "robot_blocks_graph_v1_saved";

function getPortType(nodeType, portName, direction) {
  const spec = BLOCK_CATALOG[nodeType];
  if (!spec) return null;
  const list = direction === "input" ? spec.inputs : spec.outputs;
  const found = list.find((p) => p.name === portName);
  return found ? found.type : null;
}

function computeExecutionOrder(nodes) {
  // simple deterministic priority:
  // input -> control -> sim -> sink -> other
  const prio = (type) => {
    const cat = BLOCK_CATALOG[type]?.category || "other";
    if (cat === "input") return 0;
    if (cat === "control") return 1;
    if (cat === "sim") return 2;
    if (cat === "sink") return 3;
    return 4;
  };

  const byOrder = (a, b) => {
    const pa = prio(a.type);
    const pb = prio(b.type);
    if (pa !== pb) return pa - pb;
    return (a.label + a.id).localeCompare(b.label + b.id);
  };

  return [...nodes].sort(byOrder).map((n) => n.id);
}

// Convert browser event position into "canvas coordinates" (accounts for scroll)
function eventToCanvasXY(e, canvasEl) {
  const rect = canvasEl.getBoundingClientRect();
  const x = e.clientX - rect.left + canvasEl.scrollLeft;
  const y = e.clientY - rect.top + canvasEl.scrollTop;
  return { x, y };
}

export default function App() {
  const canvasRef = useRef(null);

  // spawn offset so new nodes don't overlap
  const spawnCountRef = useRef(0);

  // max z-index tracker (bring-to-front)
  const maxZRef = useRef(1);

  // Connection UX
  const [pendingFrom, setPendingFrom] = useState(null); // { nodeId, port, msgType }
  const [toast, setToast] = useState(null);

  // Drag state
  const [drag, setDrag] = useState(null);
  // drag = { nodeId, grabDx, grabDy } where
  // grabDx = pointerX - node.x, grabDy = pointerY - node.y in canvas coords

  // Run config UI
  const [runCfg, setRunCfg] = useState({
    duration_sec: 10,
    hz: 20,
    viewer: true,
    overrides: {},
  });

  // Backend run status
  const [runStatus, setRunStatus] = useState(null); // {loading, error, run_dir, metrics}

  // ---- Initial nodes ----
  const [nodes, setNodes] = useState(() => {
    // initial z tracking
    maxZRef.current = 2;

    // keep your original default start: MuJoCo Sim + Cartesian Control
    const simId = `mujoco_sim_${uid()}`;
    const ctrlId = `cartesian_control_${uid()}`;

    return [
      {
        id: simId,
        type: "mujoco_sim",
        label: BLOCK_CATALOG.mujoco_sim.label,
        x: 260,
        y: 140,
        z: 1,
        params: deepClone(BLOCK_CATALOG.mujoco_sim.params),
      },
      {
        id: ctrlId,
        type: "cartesian_control",
        label: BLOCK_CATALOG.cartesian_control.label,
        x: 760,
        y: 140,
        z: 2,
        params: deepClone(BLOCK_CATALOG.cartesian_control.params),
      },
    ];
  });

  const [edges, setEdges] = useState([]);

  const [selectedNodeId, setSelectedNodeId] = useState(null);

  const selectedNode = useMemo(
    () => nodes.find((n) => n.id === selectedNodeId) || null,
    [nodes, selectedNodeId]
  );

  const DEFAULT_MUJOCO_MODEL = (import.meta?.env?.VITE_DEFAULT_MUJOCO_MODEL || "").trim();

  const showToast = (msg) => {
    setToast(msg);
    window.clearTimeout(showToast._t);
    showToast._t = window.setTimeout(() => setToast(null), 1800);
  };

  // ----------------------------
  // Bring-to-front (z-index)
  // ----------------------------
  const bringToFront = (nodeId) => {
    const nextZ = (maxZRef.current || 1) + 1;
    maxZRef.current = nextZ;
    setNodes((prev) => prev.map((n) => (n.id === nodeId ? { ...n, z: nextZ } : n)));
  };

  // ----------------------------
  // Spawn position (center + offset)
  // ----------------------------
  const getSpawnPosition = () => {
    const c = canvasRef.current;
    const k = spawnCountRef.current++;
    const offset = 26 * (k % 8); // gentle diagonal stack
    if (!c) return { x: 200 + offset, y: 200 + offset };

    const centerX = c.scrollLeft + c.clientWidth * 0.5;
    const centerY = c.scrollTop + c.clientHeight * 0.35;
    return {
      x: Math.round(centerX - 180 + offset),
      y: Math.round(centerY - 80 + offset),
    };
  };

  // ----------------------------
  // Node ops
  // ----------------------------
  const addNode = (type) => {
    const spec = BLOCK_CATALOG[type];
    if (!spec) return;

    const id = `${type}_${uid()}`;
    const { x, y } = getSpawnPosition();

    const nextZ = (maxZRef.current || 1) + 1;
    maxZRef.current = nextZ;

    // start from catalog defaults
    const params = deepClone(spec.params);

    // auto-fill model_path for newly created MuJoCo Sim nodes
    if (type === "mujoco_sim") {
      params.model_path = DEFAULT_MUJOCO_MODEL || params.model_path || "";
    }

    const newNode = {
      id,
      type,
      label: spec.label,
      x,
      y,
      z: nextZ,
      params,
    };

    setNodes((prev) => [...prev, newNode]);
    setSelectedNodeId(id);
    showToast("Node added");
  };

  const removeSelectedNode = () => {
    if (!selectedNodeId) return;
    const id = selectedNodeId;
    setNodes((prev) => prev.filter((n) => n.id !== id));
    setEdges((prev) => prev.filter((e) => !(e.from.startsWith(id + ".") || e.to.startsWith(id + "."))));
    setSelectedNodeId(null);
    showToast("Node deleted");
  };

  const updateSelectedParam = (key, value) => {
    if (!selectedNodeId) return;
    setNodes((prev) =>
      prev.map((n) => {
        if (n.id !== selectedNodeId) return n;
        return { ...n, params: { ...(n.params || {}), [key]: value } };
      })
    );
  };

  // ----------------------------
  // Drag logic
  // ----------------------------
  const onNodeMouseDown = (e, nodeId) => {
    e.stopPropagation();
    const c = canvasRef.current;
    if (!c) return;

    // select + bring to front
    setSelectedNodeId(nodeId);
    bringToFront(nodeId);

    const node = nodes.find((n) => n.id === nodeId);
    if (!node) return;

    const p = eventToCanvasXY(e, c);
    const grabDx = p.x - node.x;
    const grabDy = p.y - node.y;

    setDrag({ nodeId, grabDx, grabDy });
  };

  useEffect(() => {
    const onMove = (e) => {
      if (!drag) return;
      const c = canvasRef.current;
      if (!c) return;

      const p = eventToCanvasXY(e, c);
      const nx = Math.round(p.x - drag.grabDx);
      const ny = Math.round(p.y - drag.grabDy);

      setNodes((prev) => prev.map((n) => (n.id === drag.nodeId ? { ...n, x: nx, y: ny } : n)));
    };

    const onUp = () => {
      if (!drag) return;
      setDrag(null);
    };

    window.addEventListener("mousemove", onMove);
    window.addEventListener("mouseup", onUp);
    return () => {
      window.removeEventListener("mousemove", onMove);
      window.removeEventListener("mouseup", onUp);
    };
  }, [drag]);

  // ----------------------------
  // Connections
  // ----------------------------
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
    const check = canConnect({ nodeId: pendingFrom.nodeId, port: pendingFrom.port }, to);

    if (!check.ok) {
      showToast(check.reason);
      setPendingFrom(null);
      return;
    }

    const fromKey = `${pendingFrom.nodeId}.${pendingFrom.port}`;
    const toKey = `${nodeId}.${portName}`;

    setEdges((prev) => [...prev, { from: fromKey, to: toKey, msg_type: check.msg_type }]);
    setPendingFrom(null);
    showToast("Connected ✅");
  };

  const removeEdge = (idx) => setEdges((prev) => prev.filter((_, i) => i !== idx));

  // ----------------------------
  // Graph build/export/import/save/load
  // ----------------------------
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
      edges: edges.map((e) => ({ from: e.from, to: e.to, msg_type: e.msg_type })),
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

  const saveNow = () => {
    const payload = {
      nodes,
      edges,
      runCfg,
      meta: { saved_at: new Date().toISOString() },
    };
    localStorage.setItem(STORAGE_KEY, JSON.stringify(payload));
    showToast("Saved ✅");
  };

  const loadLastSaved = () => {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return showToast("No saved graph yet");
    try {
      const payload = JSON.parse(raw);
      const nextNodes = Array.isArray(payload.nodes) ? payload.nodes : [];
      const nextEdges = Array.isArray(payload.edges) ? payload.edges : [];
      const nextRunCfg = payload.runCfg || runCfg;

      // ensure z exists + compute maxZ
      let maxZ = 1;
      const fixedNodes = nextNodes.map((n, i) => {
        const z = typeof n.z === "number" ? n.z : i + 1;
        maxZ = Math.max(maxZ, z);
        return { ...n, z };
      });
      maxZRef.current = maxZ;

      setNodes(fixedNodes);
      setEdges(nextEdges);
      setRunCfg(nextRunCfg);
      setSelectedNodeId(null);
      showToast("Loaded ✅");
    } catch {
      showToast("Load failed (bad JSON)");
    }
  };

  const clearCanvas = () => {
    setNodes([]);
    setEdges([]);
    setSelectedNodeId(null);
    showToast("Cleared");
  };

  const fileInputRef = useRef(null);

  const importGraph = (file) => {
    const reader = new FileReader();
    reader.onload = () => {
      try {
        const g = JSON.parse(String(reader.result || ""));
        if (!g || g.version !== "graph.v1") throw new Error("Not a graph.v1 file");

        const gNodes = Array.isArray(g.nodes) ? g.nodes : [];
        const gEdges = Array.isArray(g.edges) ? g.edges : [];
        const gRun = g.run_config || runCfg;

        // convert graph nodes into our UI nodes
        let maxZ = 1;
        const nextNodes = gNodes.map((n, i) => {
          const ui = n.ui || {};
          const z = i + 1;
          maxZ = Math.max(maxZ, z);
          return {
            id: n.id,
            type: n.type,
            label: n.label || BLOCK_CATALOG[n.type]?.label || n.type,
            x: Number(ui.x || 0),
            y: Number(ui.y || 0),
            z,
            params: n.params || {},
          };
        });

        maxZRef.current = maxZ;

        setNodes(nextNodes);
        setEdges(
          gEdges.map((e) => ({
            from: e.from,
            to: e.to,
            msg_type: e.msg_type,
          }))
        );
        setRunCfg(gRun);
        setSelectedNodeId(null);
        showToast("Imported ✅");
      } catch (err) {
        showToast(`Import failed: ${String(err)}`);
      }
    };
    reader.readAsText(file);
  };

  // ----------------------------
  // Run via API
  // ----------------------------
  const validateForRun = () => {
    const hasMuJoCo = nodes.some((n) => n.type === "mujoco_sim");
    if (!hasMuJoCo) return { ok: false, reason: "No MuJoCo sim node" };

    for (const n of nodes) {
      if (n.type === "mujoco_sim") {
        const mp = (n.params?.model_path || "").trim();
        if (!mp) return { ok: false, reason: `Model path is empty on ${n.id}` };
      }
    }

    if (edges.length === 0) return { ok: false, reason: "No connections (edges) yet" };
    return { ok: true };
  };

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

      setRunStatus({ loading: false, run_dir: data.run_dir, metrics: data.metrics });
      showToast("Run finished ✅");
    } catch (e) {
      setRunStatus({ loading: false, error: String(e) });
      showToast(`Run failed: ${String(e)}`);
    }
  };

  // ----------------------------
  // Styles
  // ----------------------------
  const leftStyle = {
    width: 360,
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
          {Object.entries(BLOCK_CATALOG)
            .sort((a, b) => {
              const ca = a[1].category || "other";
              const cb = b[1].category || "other";
              if (ca !== cb) return ca.localeCompare(cb);
              return (a[1].label || a[0]).localeCompare(b[1].label || b[0]);
            })
            .map(([type, spec]) => (
              <button key={type} style={smallBtn} onClick={() => addNode(type)}>
                + {spec.label}
              </button>
            ))}
        </div>

        {/* Save / Load */}
        <div style={{ marginTop: 16, fontWeight: 900 }}>Save / Load</div>
        <button style={btn} onClick={saveNow}>
          Save now
        </button>
        <button style={btn} onClick={loadLastSaved}>
          Load last saved
        </button>

        <button
          style={{ ...btn, border: "1px solid #fed7aa", background: "#fff7ed" }}
          onClick={() => fileInputRef.current?.click()}
        >
          Import graph.v1.json
        </button>
        <input
          ref={fileInputRef}
          type="file"
          accept=".json,application/json"
          style={{ display: "none" }}
          onChange={(e) => {
            const f = e.target.files?.[0];
            if (f) importGraph(f);
            e.target.value = "";
          }}
        />

        <button
          style={{ ...btn, border: "1px solid #fecaca", background: "#fff1f2" }}
          onClick={clearCanvas}
        >
          Clear canvas
        </button>

        {/* Run config */}
        <div style={{ marginTop: 18, fontWeight: 900 }}>
          Run Config {runCfg.viewer ? badge("viewer: ON") : badge("viewer: OFF")}
        </div>

        <div style={{ marginTop: 10, display: "grid", gap: 10 }}>
          <label style={{ fontSize: 13, fontWeight: 800 }}>
            duration_sec
            <input
              value={runCfg.duration_sec}
              onChange={(e) => setRunCfg((p) => ({ ...p, duration_sec: Number(e.target.value || 0) }))}
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

        {/* Run */}
        <div style={{ marginTop: 16, fontWeight: 900 }}>Run</div>
        <button style={btn} onClick={() => runFromUI({ headless: true })}>
          Run ▶ (headless via API)
        </button>
        <button style={btn} onClick={() => runFromUI({ headless: false })}>
          Run ▶ (with viewer via API)
        </button>

        <div style={{ marginTop: 10, fontSize: 12, opacity: 0.7 }}>
          Backend: <code>uvicorn app.http_server:app --reload --port 8000</code>
        </div>

        {/* Export */}
        <div style={{ marginTop: 16, fontWeight: 900 }}>Export</div>
        <button style={btn} onClick={downloadGraph}>
          Export graph.v1.json
        </button>

        {/* Inspector */}
        <div style={{ marginTop: 18, fontWeight: 900 }}>Inspector</div>
        {!selectedNode ? (
          <div style={{ marginTop: 8, fontSize: 13, opacity: 0.7 }}>Click a node to edit params.</div>
        ) : (
          <div style={{ marginTop: 10 }}>
            <div style={{ fontSize: 16, fontWeight: 900 }}>{selectedNode.label}</div>
            <div style={{ fontSize: 12, opacity: 0.7, fontFamily: "monospace" }}>{selectedNode.id}</div>

            <div style={{ marginTop: 12, display: "grid", gap: 10 }}>
              {Object.entries(selectedNode.params || {}).map(([k, v]) => (
                <label key={k} style={{ fontSize: 13, fontWeight: 800 }}>
                  {k}
                  <input
                    value={String(v)}
                    onChange={(e) => {
                      const raw = e.target.value;

                      // keep model_path as string; numeric cast for others if possible
                      if (k === "model_path") {
                        updateSelectedParam(k, raw);
                        return;
                      }
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

        {/* Edges */}
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
                <div style={{ fontSize: 12, opacity: 0.7, marginTop: 4 }}>{e.msg_type}</div>
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

        {/* Last run */}
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
          background: "radial-gradient(circle at 1px 1px, rgba(0,0,0,0.08) 1px, transparent 0)",
          backgroundSize: "18px 18px",
          position: "relative",
          padding: 40,
          userSelect: drag ? "none" : "auto",
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
        {nodes.map((n) => {
          const spec = BLOCK_CATALOG[n.type];

          return (
            <div
              key={n.id}
              style={{
                position: "absolute",
                left: n.x,
                top: n.y,
                zIndex: n.z || 1,
                cursor: drag?.nodeId === n.id ? "grabbing" : "grab",
              }}
              onMouseDown={(e) => onNodeMouseDown(e, n.id)}
              onDoubleClick={(e) => {
                e.stopPropagation();
                bringToFront(n.id);
                showToast("Brought to front");
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
