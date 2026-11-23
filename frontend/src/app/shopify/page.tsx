import { ModulePlaceholder } from "@/components/ModulePlaceholder";

export default function ShopifyPage() {
  return (
    <ModulePlaceholder
      href="/shopify"
      subtitle={"Executive dashboard for the connected store."}
      capabilities={["Gross sales, net sales, refunds, discounts \u2014 each defined separately", "Orders, average order value, units sold", "Today / 7D / 30D / 90D / YTD / custom range", "Comparison against the previous equivalent period", "Revenue trend charts", "Best and worst performing products", "Low-inventory watch"]}
      requires={["Shopify app credentials (read-only scopes)", "Phase 2 data sync"]}
    />
  );
}
