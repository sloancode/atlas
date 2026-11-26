export type NavItem = {
  href: string;
  label: string;
  code: string; // short terminal-style mnemonic
  phase: number; // implementation phase that delivers it
  comingSoon?: boolean;
};

export type NavGroup = { title: string; items: NavItem[] };

export const NAV: NavGroup[] = [
  {
    title: "Business",
    items: [
      { href: "/", label: "Overview", code: "OVR", phase: 1 },
      { href: "/shopify", label: "Shopify", code: "SHP", phase: 3 },
      { href: "/autopilot", label: "Autopilot", code: "AUT", phase: 7 },
      { href: "/products", label: "Products", code: "PRD", phase: 3 },
      { href: "/profitability", label: "Profitability", code: "PNL", phase: 3 },
      { href: "/inventory", label: "Inventory", code: "INV", phase: 3 },
      { href: "/reports", label: "Business Reports", code: "RPT", phase: 4 },
    ],
  },
  {
    title: "Markets",
    items: [
      { href: "/research", label: "Stock Research", code: "RSH", phase: 5 },
      { href: "/scanner", label: "Market Scanner", code: "SCN", phase: 5 },
      { href: "/watchlists", label: "Watchlists", code: "WCH", phase: 5 },
      { href: "/portfolio", label: "Paper Portfolio", code: "PPF", phase: 5 },
      { href: "/bot", label: "Bot Run Log", code: "BOT", phase: 7 },
      { href: "/bot/rules", label: "Bot Rules", code: "BRL", phase: 7 },
      { href: "/bot/settings", label: "Bot Settings", code: "BST", phase: 7 },
    ],
  },
  {
    title: "Platform",
    items: [
      { href: "/ebay", label: "eBay", code: "EBY", phase: 6, comingSoon: true },
      { href: "/settings", label: "Settings", code: "SET", phase: 1 },
    ],
  },
];

export const ALL_NAV = NAV.flatMap((g) => g.items);
