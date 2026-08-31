import React, { useCallback } from "react";

export default function Divider({ direction = "horizontal", onResize, panelId }) {
  const handleMouseDown = useCallback(
    (e) => {
      e.preventDefault();
      e.stopPropagation();
      onResize?.(panelId, e);
    },
    [onResize, panelId]
  );

  return (
    <div
      className={`divider ${direction}`}
      onMouseDown={handleMouseDown}
    />
  );
}
