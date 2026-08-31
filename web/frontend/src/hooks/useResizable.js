import { useCallback, useRef, useState } from "react";

export function useResizable(initialSizes = {}, direction = "horizontal") {
  const [sizes, setSizes] = useState(initialSizes);
  const dragRef = useRef(null);
  const containerRef = useRef(null);

  const startResize = useCallback(
    (panelId, e) => {
      e.preventDefault();
      const container = containerRef.current;
      if (!container) return;

      const rect = container.getBoundingClientRect();
      const startPos = direction === "horizontal" ? e.clientX : e.clientY;
      const totalSize = direction === "horizontal" ? rect.width : rect.height;

      dragRef.current = { panelId, startPos, totalSize, startSizes: { ...sizes } };

      const onMove = (moveEvent) => {
        if (!dragRef.current) return;
        const currentPos =
          direction === "horizontal" ? moveEvent.clientX : moveEvent.clientY;
        const delta = currentPos - dragRef.current.startPos;
        const panelIds = Object.keys(dragRef.current.startSizes);

        setSizes((prev) => {
          const next = { ...prev };
          const idx = panelIds.indexOf(panelId);

          if (idx > 0) {
            const prevId = panelIds[idx - 1];
            const minSize = 80;
            const maxSize = dragRef.current.totalSize - minSize * (panelIds.length - 1);

            const currentStart = dragRef.current.startSizes[panelId];
            const prevStart = dragRef.current.startSizes[prevId];

            let newCurrent, newPrev;

            if (direction === "horizontal") {
              newCurrent = Math.max(minSize, Math.min(maxSize, currentStart - delta));
              newPrev = Math.max(minSize, Math.min(maxSize, prevStart + delta));
            } else {
              newCurrent = Math.max(minSize, Math.min(maxSize, currentStart - delta));
              newPrev = Math.max(minSize, Math.min(maxSize, prevStart + delta));
            }

            next[panelId] = newCurrent;
            next[prevId] = newPrev;
          }
          return next;
        });
      };

      const onUp = () => {
        dragRef.current = null;
        document.removeEventListener("mousemove", onMove);
        document.removeEventListener("mouseup", onUp);
        document.body.style.cursor = "";
        document.body.style.userSelect = "";
      };

      document.body.style.cursor =
        direction === "horizontal" ? "col-resize" : "row-resize";
      document.body.style.userSelect = "none";
      document.addEventListener("mousemove", onMove);
      document.addEventListener("mouseup", onUp);
    },
    [sizes, direction]
  );

  return { sizes, setSizes, startResize, containerRef };
}
