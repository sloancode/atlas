import { ModulePlaceholder } from "@/components/ModulePlaceholder";

export default function WatchlistsPage() {
  return (
    <ModulePlaceholder
      href="/watchlists"
      subtitle={"Track symbols you are researching."}
      capabilities={["Multiple named watchlists", "Price, change and data-delay labels", "Notes per symbol", "Links into research reports"]}
      requires={["A market data key for prices"]}
    />
  );
}
