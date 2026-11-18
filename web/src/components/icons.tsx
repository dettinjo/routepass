import type { SVGProps } from "react";

const base = { fill: "none", stroke: "currentColor", strokeWidth: 1.8, strokeLinecap: "round", strokeLinejoin: "round", viewBox: "0 0 24 24" } as const;
type P = SVGProps<SVGSVGElement>;

export const IconHome = (p: P) => (<svg {...base} {...p}><path d="M3 11l9-7 9 7" /><path d="M5 10v10h14V10" /></svg>);
export const IconList = (p: P) => (<svg {...base} {...p}><path d="M8 6h13M8 12h13M8 18h13" /><circle cx="4" cy="6" r="1" /><circle cx="4" cy="12" r="1" /><circle cx="4" cy="18" r="1" /></svg>);
export const IconChart = (p: P) => (<svg {...base} {...p}><path d="M4 20V10M10 20V4M16 20v-7M22 20H2" /></svg>);
export const IconSync = (p: P) => (<svg {...base} {...p}><path d="M20 7H8a4 4 0 0 0-4 4v1" /><path d="M17 4l3 3-3 3" /><path d="M4 17h12a4 4 0 0 0 4-4v-1" /><path d="M7 20l-3-3 3-3" /></svg>);
export const IconSettings = (p: P) => (<svg {...base} {...p}><circle cx="12" cy="12" r="3" /><path d="M19.4 15a1.7 1.7 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.8-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-1.1-1.5 1.7 1.7 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.8 1.7 1.7 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1a1.7 1.7 0 0 0 1.5-1.1 1.7 1.7 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.8.3H9a1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.8V9a1.7 1.7 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1z" /></svg>);
export const IconRefresh = (p: P) => (<svg {...base} {...p}><path d="M21 12a9 9 0 1 1-2.6-6.4" /><path d="M21 3v6h-6" /></svg>);
export const IconArrowUp = (p: P) => (<svg {...base} {...p}><path d="M12 19V5M5 12l7-7 7 7" /></svg>);
export const IconArrowDown = (p: P) => (<svg {...base} {...p}><path d="M12 5v14M19 12l-7 7-7-7" /></svg>);
export const IconLeft = (p: P) => (<svg {...base} {...p}><path d="M15 18l-6-6 6-6" /></svg>);
export const IconRight = (p: P) => (<svg {...base} {...p}><path d="M9 18l6-6-6-6" /></svg>);
export const IconPlus = (p: P) => (<svg {...base} {...p}><path d="M12 5v14M5 12h14" /></svg>);
export const IconTrash = (p: P) => (<svg {...base} {...p}><path d="M3 6h18M8 6V4h8v2M6 6l1 14h10l1-14" /></svg>);
export const IconLock = (p: P) => (<svg {...base} {...p}><rect x="5" y="11" width="14" height="10" rx="2" /><path d="M8 11V7a4 4 0 0 1 8 0v4" /></svg>);
export const IconExternal = (p: P) => (<svg {...base} {...p}><path d="M14 4h6v6M20 4l-9 9M18 14v6H4V6h6" /></svg>);
export const IconDownload = (p: P) => (<svg {...base} {...p}><path d="M12 4v12M6 10l6 6 6-6M4 20h16" /></svg>);
export const IconX = (p: P) => (<svg {...base} {...p}><path d="M6 6l12 12M18 6L6 18" /></svg>);
