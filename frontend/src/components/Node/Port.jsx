export default function Port({ type, label, dataType }) {
  const isInput = type === "input";

  return (
    <div
      style={{
        display: "flex",
        alignItems: "center",
        gap: 10,
        margin: "8px 0",
        userSelect: "none",
      }}
    >
      <div
        style={{
          width: 14,
          height: 14,
          borderRadius: "50%",
          background: isInput ? "#2563eb" : "#16a34a",
          border: "2px solid rgba(0,0,0,0.65)",
          boxShadow: "0 1px 2px rgba(0,0,0,0.15)",
        }}
        title={isInput ? "input" : "output"}
      />
      <div style={{ fontSize: 14 }}>
        <b>{label}</b> <span style={{ opacity: 0.65 }}>({dataType})</span>
      </div>
    </div>
  );
}
