import { ModulePlaceholder } from "@/components/ModulePlaceholder";

export default function ScannerPage() {
  return (
    <ModulePlaceholder
      href="/scanner"
      subtitle={"Configurable screens that explain why each result appeared. Scores are not probabilities."}
      capabilities={["Long-term, swing, momentum, value, growth, recovery, ETF categories", "User-defined criteria", "Per-result explanation of matched rules", "Data freshness on every row"]}
      requires={["MASSIVE_API_KEY and/or FMP_API_KEY"]}
    />
  );
}
