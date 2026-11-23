import { ModulePlaceholder } from "@/components/ModulePlaceholder";

export default function ProfitabilityPage() {
  return (
    <ModulePlaceholder
      href="/profitability"
      subtitle={"Profit, not just revenue. Costs you have not entered are flagged, never assumed."}
      capabilities={["Editable COGS, shipping, packaging, transaction fees, advertising, other opex", "Gross profit and gross margin", "Contribution margin and estimated net operating profit", "Break-even sales", "Profit per product and per order", "Incomplete / estimated labels wherever a cost is missing"]}
      requires={["Shopify app credentials (read-only scopes)", "Your cost inputs (entered in this screen)"]}
    />
  );
}
