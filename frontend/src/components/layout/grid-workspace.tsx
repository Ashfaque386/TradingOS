"use client";

import "react-grid-layout/css/styles.css";

import { useCallback, useState } from "react";
import { GripVertical } from "lucide-react";
import {
  Responsive,
  useContainerWidth,
  type Layout,
  type LayoutItem,
  type ResponsiveLayouts,
} from "react-grid-layout";

export interface GridPanel {
  id: string;
  node: React.ReactNode;
  defaultLayout: Pick<LayoutItem, "x" | "y" | "w" | "h" | "minW" | "minH">;
}

const BREAKPOINTS = { lg: 1200, md: 996, sm: 768, xs: 480, xxs: 0 };
const COLS = { lg: 12, md: 10, sm: 6, xs: 2, xxs: 1 };

function loadStoredLayouts(storageKey: string, fallback: ResponsiveLayouts): ResponsiveLayouts {
  if (typeof window === "undefined") return fallback;
  try {
    const raw = window.localStorage.getItem(storageKey);
    return raw ? (JSON.parse(raw) as ResponsiveLayouts) : fallback;
  } catch {
    return fallback;
  }
}

/** REL-011 E11.2: draggable/resizable panel grid, persisted to localStorage (a genuine local UI
 * preference -- no backend surface for layout exists or is needed, matching the existing
 * auth-token-in-localStorage precedent). Dragging is restricted to the `.grid-drag-handle` icon
 * injected into each panel's corner (via `dragConfig.handle`), not the whole panel -- critical
 * for the Kill Switch panel, whose SlideToHalt gesture (kill-switch-button.tsx) is a separate
 * framer-motion `drag="x"` on an inner element that must keep receiving its own pointer events
 * untouched by react-grid-layout's own drag listener. */
export function GridWorkspace({ storageKey, panels }: { storageKey: string; panels: GridPanel[] }) {
  const { width, containerRef, mounted } = useContainerWidth();

  const defaultLayouts: ResponsiveLayouts = {
    lg: panels.map((p) => ({ i: p.id, ...p.defaultLayout })),
  };

  const [layouts, setLayouts] = useState<ResponsiveLayouts>(() =>
    loadStoredLayouts(storageKey, defaultLayouts),
  );

  const handleLayoutChange = useCallback(
    (_layout: Layout, allLayouts: ResponsiveLayouts) => {
      setLayouts(allLayouts);
      window.localStorage.setItem(storageKey, JSON.stringify(allLayouts));
    },
    [storageKey],
  );

  return (
    <div ref={containerRef}>
      {mounted && (
        <Responsive
          layouts={layouts}
          breakpoints={BREAKPOINTS}
          cols={COLS}
          width={width}
          rowHeight={50}
          margin={[16, 16]}
          dragConfig={{ handle: ".grid-drag-handle" }}
          onLayoutChange={handleLayoutChange}
        >
          {panels.map((p) => (
            <div key={p.id} className="relative">
              <div
                className="grid-drag-handle absolute right-2 top-2 z-10 cursor-grab rounded-md p-1 text-zinc-600 transition hover:bg-white/5 hover:text-zinc-300 active:cursor-grabbing"
                title="Drag to rearrange"
              >
                <GripVertical size={14} />
              </div>
              {p.node}
            </div>
          ))}
        </Responsive>
      )}
    </div>
  );
}
