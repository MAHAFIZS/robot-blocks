import Port from "./Port";

export default function BlockNode({
  title,
  id,
  inputs = [],
  outputs = [],
  onOutputMouseDown,
  onInputMouseUp,
}) {
  return (
    <div
      style={{
        width: 360,
        padding: 18,
        borderRadius: 18,
        background: "white",
        border: "1px solid #e5e7eb",
        boxShadow: "0 10px 28px rgba(0,0,0,0.08)",
      }}
    >
      <div style={{ display: "flex", justifyContent: "space-between", gap: 12 }}>
        <div>
          <div style={{ fontSize: 34, fontWeight: 900, lineHeight: 1.05 }}>{title}</div>
          <div style={{ fontSize: 13, opacity: 0.65, marginTop: 6, fontFamily: "monospace" }}>
            {id}
          </div>
        </div>
      </div>

      <div style={{ marginTop: 14 }}>
        <div style={{ fontWeight: 900, fontSize: 18 }}>Inputs</div>
        {inputs.map((p) => (
          <div key={p.name} onMouseUp={() => onInputMouseUp?.(p)}>
            <Port type="input" label={p.name} dataType={p.type} />
          </div>
        ))}
      </div>

      <div style={{ marginTop: 14 }}>
        <div style={{ fontWeight: 900, fontSize: 18 }}>Outputs</div>
        {outputs.map((p) => (
          <div key={p.name} onMouseDown={() => onOutputMouseDown?.(p)}>
            <Port type="output" label={p.name} dataType={p.type} />
          </div>
        ))}
      </div>
    </div>
  );
}
