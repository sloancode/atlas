export type NavItem = { href: string; label: string; code: string };
export type NavGroup = { title: string; items: NavItem[] };

export const NAV: NavGroup[] = [
  {
    title: "Trading bot",
    items: [
      { href: "/", label: "Bot dashboard", code: "BOT" },
      { href: "/bot/runs", label: "Run log", code: "LOG" },
      { href: "/bot/rules", label: "Rules & limits", code: "RUL" },
    ],
  },
  {
    title: "Research",
    items: [
      { href: "/research", label: "Stock Research", code: "RSH" },
      { href: "/scanner", label: "Market Scanner", code: "SCN" },
      { href: "/watchlists", label: "Watchlists", code: "WCH" },
    ],
  },
  { title: "System", items: [{ href: "/settings", label: "Settings", code: "SET" }] },
];

export const ALL_NAV = NAV.flatMap((g) => g.items);
