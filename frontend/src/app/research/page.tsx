import { ModulePlaceholder } from "@/components/ModulePlaceholder";

export default function ResearchPage() {
  return (
    <ModulePlaceholder
      href="/research"
      subtitle={"Company and ETF research reports. You make every investment decision."}
      capabilities={["Price history, volume, moving averages, RSI, MACD", "Relative strength, volatility, support/resistance estimates", "Earnings dates and financial statements", "Growth, free cash flow, debt, cash, valuation", "AI report: overview, competition, health, risks, bull/bear case, thesis, events to monitor"]}
      requires={["MASSIVE_API_KEY and/or FMP_API_KEY", "SEC_USER_AGENT for EDGAR filings", "ANTHROPIC_API_KEY for AI reports"]}
    />
  );
}
