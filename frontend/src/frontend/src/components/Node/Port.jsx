export default function Port({ type, label, dataType }) {
  const isInput = type === "input";

  return (
    <div
      style={{
        display: "flex",
        alignItems: "center",
        gap: 8,
        margin: "6px 0",
        cursor: "pointer",
        userSelect: "none",
      }}
    >
      {/* Dot */}
      <div
        style={{
          width: 14,
          height: 14,
          borderRadius: "50%",
          background: isInput ? "#2563eb" : "#16a34a", // blue / green
          border: "2px solid #111",
        }}
      />

      {/* Label */}
      <div style={{ fontSize: 14 }}>
        <b>{label}</b>{" "}
        <span style={{ opacity: 0.6 }}>({dataType})</span>
      </div>
    </div>
  );
}
