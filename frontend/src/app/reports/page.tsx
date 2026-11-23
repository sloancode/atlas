import { ModulePlaceholder } from "@/components/ModulePlaceholder";

export default function ReportsPage() {
  return (
    <ModulePlaceholder
      href="/reports"
      subtitle={"Daily and weekly business reports grounded in retrieved data."}
      capabilities={["Daily report: revenue, orders, best/worst products, inventory alerts, profitability, changes, 3 areas to investigate", "Weekly report with trends and comparisons", "Facts, estimates and AI interpretation shown separately", "AI business analyst Q&A with cited data", "Export (Markdown / PDF / CSV)"]}
      requires={["Shopify app credentials (read-only scopes)", "ANTHROPIC_API_KEY for AI narrative"]}
    />
  );
}
