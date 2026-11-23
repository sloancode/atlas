import { ModulePlaceholder } from "@/components/ModulePlaceholder";

export default function PortfolioPage() {
  return (
    <ModulePlaceholder
      href="/portfolio"
      subtitle={"SIMULATED paper trading. No brokerage connection, no real orders."}
      capabilities={["Virtual cash", "Simulated positions with entry prices", "Position values and unrealized P&L", "Historical performance", "Trade journal", "Violet SIMULATED labels on every value"]}
      requires={["A market data key for prices"]}
    />
  );
}
