import katex from "katex";
import "katex/dist/katex.min.css";
import { BookOpen, Clock3, Sigma } from "lucide-react";
import { PageTitle, Panel } from "../components/UI";
import "../styles/research-notes.css";

// Only equations written in this module enter KaTeX. MathML is included for
// screen readers and all fonts and styles are bundled in the local build.
function Equation({ tex }: { tex: string }) {
  const html = katex.renderToString(tex, {
    displayMode: true,
    output: "htmlAndMathml",
    throwOnError: true,
    trust: false,
  });
  return (
    <div className="rn-equation" dangerouslySetInnerHTML={{ __html: html }} />
  );
}

const predictors = [
  [
    "Latest log return",
    "The change from the previous close to the forecast close, expressed in log-return units.",
  ],
  [
    "5-session volatility",
    "The sample standard deviation of the five most recent returns.",
  ],
  [
    "10-session volatility",
    "The same measure over the ten most recent returns.",
  ],
  [
    "20-session volatility",
    "A longer view of recent variability using twenty returns.",
  ],
  [
    "5-session log momentum",
    "The sum of the latest five log returns, retaining the direction of the cumulative move.",
  ],
];

export default function Methodology() {
  return (
    <div className="rn-page">
      <PageTitle
        eyebrow="Research guide"
        title="Methodology"
        description="Follow a forecast from an adjusted SPY closing price to a measured error five trading sessions later."
      />

      <Panel
        title="The research pipeline"
        description="The close of the forecast session separates known history from the five returns still to come."
      >
        <div className="rn-pipeline">
          <section aria-labelledby="pipeline-known">
            <h3 id="pipeline-known">
              <Clock3 size={18} aria-hidden="true" /> At the forecast close
            </h3>
            <ol>
              {[
                "SPY adjusted closing prices",
                "Daily log returns",
                "Trailing volatility and momentum",
                "Standardization with frozen training values",
                "Frozen Ridge prediction",
                "Timestamped forecast record",
              ].map((step) => (
                <li key={step}>{step}</li>
              ))}
            </ol>
          </section>
          <section aria-labelledby="pipeline-future">
            <h3 id="pipeline-future">
              <Sigma size={18} aria-hidden="true" /> After the target window
            </h3>
            <ol>
              {[
                "Five future trading sessions close",
                "Observed sample volatility",
                "Signed prediction error",
                "Evaluation across eligible forecasts",
              ].map((step) => (
                <li key={step}>{step}</li>
              ))}
            </ol>
            <p>
              The recorded forecast stays fixed while the target unfolds. The
              2027 protocol defers comparison until the formal evaluation.
            </p>
          </section>
        </div>
      </Panel>

      <div className="rn-grid">
        <Panel title="Adjusted closing prices">
          <Equation
            tex={String.raw`P_t=\text{SPY adjusted closing price at session }t`}
          />
          <p>
            SPY is an exchange-traded fund that tracks the S&amp;P 500. Adjusted
            closes account for splits and distributions, which can change the
            quoted share price mechanically. The project takes the explicit
            adjusted-close field from one saved Yahoo Finance vintage.
          </p>
          <p>
            Session indices follow the NYSE trading calendar. Twenty daily
            returns require twenty-one consecutive observed prices.
          </p>
        </Panel>
        <Panel title="Daily log returns">
          <Equation
            tex={String.raw`r_t=\ln\!\left(\frac{P_t}{P_{t-1}}\right)`}
          />
          <p>
            A log return measures a relative price change. Adding log returns
            across consecutive sessions gives the log change over the whole
            interval.
          </p>
          <div className="rn-example">
            <strong>Illustrative price move</strong>
            <p>
              If an adjusted close moves from $100 to $101, the log return is
              ln(101/100) ≈ 0.00995, or 0.995% in log-return units.
            </p>
          </div>
        </Panel>
      </div>

      <Panel
        title="Historical volatility"
        description="Each benchmark carries a recent estimate of daily variability forward into the next five-session window."
      >
        <Equation
          tex={String.raw`\bar r_{t,w}=\frac{1}{w}\sum_{j=0}^{w-1}r_{t-j}`}
        />
        <Equation
          tex={String.raw`s_{t,w}=\sqrt{\frac{1}{w-1}\sum_{j=0}^{w-1}\left(r_{t-j}-\bar r_{t,w}\right)^2}`}
        />
        <p>
          Subtract the window mean from each return, square the deviations,
          average with divisor <em>w − 1</em>, and take the square root.
          Estimating the mean uses one degree of freedom. The sample convention{" "}
          <code>ddof=1</code> applies to all three trailing windows and the
          future target.
        </p>
        <p>
          The 5-session estimate responds quickly when large returns enter or
          leave the window. The 20-session estimate retains those returns
          longer. Both are daily, unannualized volatility.
        </p>
      </Panel>

      <div className="rn-grid">
        <Panel
          title="The five predictors"
          description="The trained model receives these values in the order shown, with returns and volatility in decimal units."
        >
          <ol className="rn-predictors">
            {predictors.map(([name, description]) => (
              <li key={name}>
                <strong>{name}</strong>
                <p>{description}</p>
              </li>
            ))}
          </ol>
          <Equation tex={String.raw`m_{t,5}=\sum_{j=0}^{4}r_{t-j}`} />
        </Panel>
        <Panel title="Frozen Ridge regression">
          <Equation tex={String.raw`z_{t,k}=\frac{x_{t,k}-\mu_k}{\sigma_k}`} />
          <p>
            The training mean and scale put each predictor on a comparable
            scale. These values stay fixed when a new price arrives.
          </p>
          <Equation
            tex={String.raw`\hat y_t=\max\!\left(0,\beta_0+z_t^\top\beta\right)`}
          />
          <p>
            The intercept and five coefficients translate standardized inputs
            into a predicted daily-return standard deviation. The zero floor
            keeps the prediction in its physical range.
          </p>
          <p>
            Ridge fits coefficients with an L2 penalty on their squared
            magnitudes. This limits how strongly the fitted weights can shift
            when the 5-, 10- and 20-session predictors carry similar
            information. The prepared model uses α = 1.
          </p>
        </Panel>
      </div>

      <Panel title="The observed five-session target">
        <Equation
          tex={String.raw`\bar r_{t,+}=\tfrac15\sum_{j=1}^5 r_{t+j},\qquad y_t=\sqrt{\tfrac14\sum_{j=1}^{5}(r_{t+j}-\bar r_{t,+})^2}`}
        />
        <p>
          After the fifth session closes, one archived vintage supplies the
          origin price and the next five adjusted closes. Their five log returns
          produce one sample standard deviation for the entire window. Until the
          fifth close, a required return is still unknown.
        </p>
      </Panel>

      <Panel
        title="Measuring forecast errors"
        description="Score all methods on the same eligible forecast observations."
      >
        <Equation tex={String.raw`e_i=100\!\left(\hat y_i-y_i\right)`} />
        <p>
          Multiplying a difference in decimal volatility by 100 gives percentage
          points. A positive error means the forecast was above the observed
          volatility.
        </p>
        <div className="rn-metrics">
          <div>
            <Equation tex={String.raw`\mathrm{MAE}=\tfrac1n\sum_i|e_i|`} />
            <p>Average magnitude of the errors, in percentage points.</p>
          </div>
          <div>
            <Equation tex={String.raw`\mathrm{MSE}=\tfrac1n\sum_i e_i^2`} />
            <p>Average squared error, in squared percentage points.</p>
          </div>
          <div>
            <Equation
              tex={String.raw`\mathrm{RMSE}=\sqrt{\tfrac1n\sum_i e_i^2}`}
            />
            <p>
              Square root of the average squared error. Larger misses carry more
              weight.
            </p>
          </div>
          <div>
            <Equation tex={String.raw`\mathrm{Bias}=\tfrac1n\sum_i e_i`} />
            <p>
              Average signed error. Positive and negative misses can cancel.
            </p>
          </div>
        </div>
        <div className="rn-example">
          <strong>Illustrative comparison across two forecasts</strong>
          <p>
            A 1.4% forecast followed by 1.0% observed volatility has an error of
            +0.4 pp. A second error of −0.2 pp gives MAE 0.3 pp, MSE 0.10 pp²,
            RMSE about 0.316 pp, and bias +0.1 pp. Here <em>n</em> counts the
            two forecast observations. The benchmark window length determines
            the inputs to each forecast.
          </p>
        </div>
      </Panel>
      <a
        className="rn-source"
        href="https://github.com/pandeyp1426/spy-volatility-forecasting/blob/main/docs/protocols/research_design.md"
      >
        <BookOpen size={16} aria-hidden="true" /> Research design and
        definitions
      </a>
    </div>
  );
}
