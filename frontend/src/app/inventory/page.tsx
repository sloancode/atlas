import { ModulePlaceholder } from "@/components/ModulePlaceholder";

export default function InventoryPage() {
  return (
    <ModulePlaceholder
      href="/inventory"
      subtitle={"Coverage and stockout risk from historical sales velocity. Alerts only \u2014 stock is never changed."}
      capabilities={["Low-stock and overstock detection", "Days of cover from sales velocity", "Faster-than-expected sellers", "Declining-demand products", "Stockout risk", "Configurable alert thresholds"]}
      requires={["Shopify app credentials (read-only scopes)", "Phase 2 data sync"]}
    />
  );
}
