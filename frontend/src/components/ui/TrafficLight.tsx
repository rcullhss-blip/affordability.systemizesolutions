import { clsx } from "clsx";

type Light = "GREEN" | "AMBER" | "RED";

const CONFIG: Record<Light, { label: string; classes: string; dot: string }> = {
  GREEN: {
    label: "Strong Case",
    classes: "bg-green-900/40 text-green-300 border border-green-700",
    dot: "bg-green-400",
  },
  AMBER: {
    label: "Borderline Case",
    classes: "bg-amber-900/40 text-amber-300 border border-amber-700",
    dot: "bg-amber-400",
  },
  RED: {
    label: "Not Viable",
    classes: "bg-red-900/40 text-red-400 border border-red-800",
    dot: "bg-red-500",
  },
};

export function TrafficLightBadge({ light }: { light: Light | string }) {
  const cfg = CONFIG[light as Light] ?? CONFIG.RED;
  return (
    <span className={clsx("inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-semibold", cfg.classes)}>
      <span className={clsx("w-2 h-2 rounded-full flex-shrink-0", cfg.dot)} />
      {cfg.label}
    </span>
  );
}
