"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { NAV } from "@/lib/nav";

export function Sidebar() {
  const pathname = usePathname();
  return (
    <aside className="flex w-56 shrink-0 flex-col border-r border-border bg-panel">
      <div className="flex h-11 items-center gap-2 border-b border-border px-4">
        <span className="num text-[15px] font-semibold tracking-[0.2em] text-accent">ATLAS</span>
        <span className="text-[10px] uppercase tracking-wider text-faint">paper bot</span>
      </div>
      <nav className="flex-1 overflow-y-auto py-2" aria-label="Main">
        {NAV.map((group) => (
          <div key={group.title} className="mb-2">
            <div className="px-4 pb-1 pt-3 text-[10px] font-medium uppercase tracking-[0.14em] text-faint">
              {group.title}
            </div>
            {group.items.map((item) => {
              const active = item.href === "/" ? pathname === "/" : pathname.startsWith(item.href);
              return (
                <Link
                  key={item.href}
                  href={item.href}
                  aria-current={active ? "page" : undefined}
                  className={`flex items-center gap-3 border-l-2 px-4 py-[7px] transition-colors ${
                    active
                      ? "border-accent bg-panel-2 text-text"
                      : "border-transparent text-dim hover:bg-panel-2 hover:text-text"
                  }`}
                >
                  <span className={`num w-8 text-[10px] ${active ? "text-accent" : "text-faint"}`}>
                    {item.code}
                  </span>
                  <span className="flex-1">{item.label}</span>
                </Link>
              );
            })}
          </div>
        ))}
      </nav>
      <div className="border-t border-border px-4 py-3 text-[11px] leading-relaxed text-faint">
        Paper trading only (simulated money). This website never places orders; the scheduled bot does, within fixed limits.
      </div>
    </aside>
  );
}
