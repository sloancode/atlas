import { getPresets, getWatchlists } from "@/lib/api";
import { ScannerPanel } from "@/components/ScannerPanel";
import { EmptyState, PageHeader } from "@/components/ui";

export default async function ScannerPage() {
  const [presets, lists] = await Promise.all([getPresets(), getWatchlists()]);
  return (
    <>
      <PageHeader code="SCN" title="Market Scanner"
        subtitle="Rule-based screens over symbols you choose. Each result lists every rule with its actual value. Missing data never counts as a match, and there are no scores or probabilities." />
      {!presets.ok ? <EmptyState title="Scanner unavailable">{presets.error}</EmptyState> : (
        <ScannerPanel presets={presets.data.presets} metrics={presets.data.metrics}
          watchlists={lists.ok ? lists.data.map((w) => ({ id: w.id, name: w.name, count: w.items.length })) : []} />
      )}
    </>
  );
}
