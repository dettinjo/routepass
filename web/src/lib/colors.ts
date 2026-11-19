export const FAMILIES = ["ride", "run", "walk", "winter", "water", "other"] as const;
export type Family = (typeof FAMILIES)[number];

export const FAMILY_LABEL: Record<string, string> = {
  ride: "Ride", run: "Run", walk: "Walk & Hike", winter: "Winter", water: "Water", other: "Other",
};

/** Fixed categorical order — colour follows the family, never its rank. */
export const familyColor = (f: string) => `var(--series-${Math.max(1, FAMILIES.indexOf(f as Family) + 1) || 6})`;

export const SEQ = ["var(--seq-0)", "var(--seq-1)", "var(--seq-2)", "var(--seq-3)", "var(--seq-4)", "var(--seq-5)", "var(--seq-6)"];

/** Resolve a CSS custom property to a concrete colour (follows aliases such as --line-1: var(--text-primary)),
 *  for canvas/Leaflet code that cannot use var(). */
export function cssVar(name: string): string {
  let v = name.startsWith("var(") ? name.slice(4, -1) : name;
  const style = getComputedStyle(document.documentElement);
  for (let i = 0; i < 4; i++) {
    const out = style.getPropertyValue(v).trim();
    if (!out) return "#888";
    if (!out.startsWith("var(")) return out;
    v = out.slice(4, -1);
  }
  return "#888";
}

/** Year-over-year lines: older years in a quiet neutral ramp, the current year in the accent. */
export function yearColor(indexFromNewest: number): string {
  return indexFromNewest === 0 ? "var(--accent)" : `var(--year-${Math.max(1, 5 - indexFromNewest)})`;
}

/** Amount scale for heatmaps: steps of one hue (a sport's colour when one is selected, otherwise ink). */
export function heatScale(base = "var(--heat)"): string[] {
  return ["var(--surface-3)", ...[16, 30, 46, 62, 80, 100].map((p) => `color-mix(in srgb, ${base} ${p}%, var(--surface-2))`)];
}

/** Training-plan disciplines use the same palette as everything else. */
export const PLAN_SPORT_FAMILY: Record<string, string> = {
  run: "run", trail_run: "run", bike: "ride", ride: "ride", cycling: "ride", swim: "water",
  brick: "ride", strength: "other", recovery: "other", rest: "other",
};
export const planSportColor = (sport: string) => familyColor(PLAN_SPORT_FAMILY[sport] ?? "other");
