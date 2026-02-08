export default function Port({
  type,        // "input" | "output"
  label,
  dataType,
  onMouseDown,
  onMouseUp,
}) {
  const isInput = type === "input";

  return (
    <div
      style={{
        display: "flex",
        alignItems: "center",
        margin: "6px 0",
        cursor: "pointer",
        justifyContent: isInput ? "flex-start" : "flex-end",
        gap: "8px",
      }}
      onMouseDown={onMouseDown}
      onMouseUp={onMouseUp}
    >
      {isInput && (
        <div
          style={{
            width: 12,
            height: 12,
            borderRadius: "50%",
            backgroundColor: "#2563eb", // blue
            border: "2px solid #1e40af",
          }}
        />
      )}

      <span style={{ fontSize: 14 }}>
        <b>{label}</b>{" "}
        <span style={{ opacity: 0.6 }}>({dataType})</span>
      </span>

      {!isInput && (
        <div
          style={{
            width: 12,
            height: 12,
            borderRadius: "50%",
            backgroundColor: "#16a34a", // green
            border: "2px solid #166534",
          }}
        />
      )}
    </div>
  );
}
