import { ALL_NAV } from "@/lib/nav";
import { EmptyState, PageHeader, Panel } from "./ui";

export function ModulePlaceholder({
  href,
  subtitle,
  capabilities,
  requires,
}: {
  href: string;
  subtitle: string;
  capabilities: string[];
  requires: string[];
}) {
  const item = ALL_NAV.find((n) => n.href === href)!;
  return (
    <>
      <PageHeader code={item.code} title={item.label} subtitle={subtitle} />
      <div className="grid gap-4 lg:grid-cols-3">
        <div className="lg:col-span-2">
          <EmptyState title={item.comingSoon ? "Coming soon" : `Arrives in Phase ${item.phase}`}>
            No data is shown here until this module is built and its data source is connected.
            ATLAS does not display placeholder numbers.
          </EmptyState>
        </div>
        <Panel title="Requires">
          <ul className="list-disc space-y-1 pl-4 text-dim">
            {requires.map((r) => (
              <li key={r}>{r}</li>
            ))}
          </ul>
        </Panel>
        <Panel title="Planned capabilities" className="lg:col-span-3">
          <ul className="grid gap-x-6 gap-y-1 text-dim sm:grid-cols-2 xl:grid-cols-3">
            {capabilities.map((c) => (
              <li key={c} className="before:mr-2 before:text-faint before:content-['›']">
                {c}
              </li>
            ))}
          </ul>
        </Panel>
      </div>
    </>
  );
}
