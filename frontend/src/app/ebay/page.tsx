import { ModulePlaceholder } from "@/components/ModulePlaceholder";

export default function EbayPage() {
  return (
    <ModulePlaceholder
      href="/ebay"
      subtitle={"eBay Sell API module. Intentionally not connected yet."}
      capabilities={["Inventory API: listings and stock", "Fulfillment API: orders and refunds", "Account API: policies and fees", "Analytics: traffic and sales performance", "Shopify vs eBay comparison without double-counting", "Cross-platform product identity (one product, two channels)"]}
      requires={["Your approval to start the eBay OAuth integration", "eBay developer keys (later)"]}
    />
  );
}
