import Port from "./Port";

export default function BlockNode({
  title,
  id,
  inputs,
  outputs,
  onOutputMouseDown,
  onInputMouseUp,
}) {
  return (
    <div style={{ width: 320, padding: 16, borderRadius: 16, background: "white", border: "1px solid #e5e7eb" }}>
      <h2 style={{ margin: 0 }}>{title}</h2>
      <div style={{ fontSize: 12, opacity: 0.6 }}>{id}</div>

      <div style={{ marginTop: 12 }}>
        <b>Inputs</b>
        {inputs.map((p) => (
          <div key={p.name} onMouseUp={() => onInputMouseUp?.(p)}>
            <Port type="input" label={p.name} dataType={p.type} />
          </div>
        ))}
      </div>

      <div style={{ marginTop: 12 }}>
        <b>Outputs</b>
        {outputs.map((p) => (
          <div key={p.name} onMouseDown={() => onOutputMouseDown?.(p)}>
            <Port type="output" label={p.name} dataType={p.type} />
          </div>
        ))}
      </div>
    </div>
  );
}
