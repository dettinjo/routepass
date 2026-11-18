export const FAMILIES = ["ride", "run", "walk", "winter", "water", "other"] as const;
export type Family = (typeof FAMILIES)[number];

export const FAMILY_LABEL: Record<string, string> = {
  ride: "Ride", run: "Run", walk: "Walk & Hike", winter: "Winter", water: "Water", other: "Other",
};

/** Fixed categorical order — colour follows the family, never its rank. */
export const familyColor = (f: string) => `var(--series-${Math.max(1, FAMILIES.indexOf(f as Family) + 1) || 6})`;

export const SEQ = ["var(--seq-0)", "var(--seq-1)", "var(--seq-2)", "var(--seq-3)", "var(--seq-4)", "var(--seq-5)", "var(--seq-6)"];

export function cssVar(name: string): string {
  const v = name.startsWith("var(") ? name.slice(4, -1) : name;
  return getComputedStyle(document.documentElement).getPropertyValue(v).trim() || "#888";
}
