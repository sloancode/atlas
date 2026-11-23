import { ModulePlaceholder } from "@/components/ModulePlaceholder";

export default function ProductsPage() {
  return (
    <ModulePlaceholder
      href="/products"
      subtitle={"Analytics profile for every product, with an explained opportunity score."}
      capabilities={["Per-product profile: image, SKU, price, units, revenue, order frequency, inventory", "Sales growth and performance ranking", "Accelerating and decelerating products", "High stock / weak demand and low stock / strong demand", "Seasonality signals", "Opportunity score with a written explanation of every factor"]}
      requires={["Shopify app credentials (read-only scopes)", "Phase 2 data sync"]}
    />
  );
}
