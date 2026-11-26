import { z } from "zod";
import { eastern } from "../services/format";
import { localPreview, useLocalFeed } from "../services/local";

const schema = z.object({
  price: z.number().finite().positive(), as_of: z.string().datetime({offset: true}),
  fetched_at: z.string().datetime({offset: true}), market_open: z.boolean(), delayed: z.boolean(),
}).strict();
const widget = "https://www.tradingview-widget.com/embed-widget/single-quote/?locale=en#" +
  encodeURIComponent(JSON.stringify({symbol: "AMEX:SPY", colorTheme: "dark", isTransparent: true, width: "100%"}));

export function MarketQuote() {
  const {value, failed} = useLocalFeed("quote.json", schema);
  if (!localPreview()) return <section className="quote-card embedded" aria-label="SPY market price">
    <iframe title="SPY quote from TradingView" src={widget} referrerPolicy="strict-origin-when-cross-origin" />
    <a href="https://www.tradingview.com/symbols/AMEX-SPY/" target="_blank" rel="noreferrer">SPY on TradingView ↗</a>
  </section>;
  return <section className="quote-card" aria-label="SPY market price">
    <div><h2>SPY price</h2>
      {value && <strong className="quote-price">${value.price.toFixed(2)}</strong>}
    </div>
    <div className="quote-meta">
      {value && <><span>{failed ? "Last available quote" : value.market_open ? "Market open" : "Market closed"}{value.delayed && " · Delayed quote"}</span>
        <small title="Yahoo Finance · regular-session one-minute close">{eastern(value.as_of)}</small></>}
      {failed && <small role="status">Quote refresh unavailable.</small>}
      {!failed && !value && <small role="status">Loading price…</small>}
    </div>
  </section>;
}
