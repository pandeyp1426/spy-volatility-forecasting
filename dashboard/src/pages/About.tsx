import { BookOpen, Github } from "lucide-react";
import { Link } from "react-router-dom";
import { PageTitle, Panel, Milestones, repo } from "../components/UI";
export default function About() {
  return (
    <div className="stack">
      <PageTitle
        eyebrow="Research project"
        title="About the research"
        description="Machine Learning Research for Short-Term Market Volatility Forecasting"
      />
      <Panel title="Can recent prices tell us how variable the next week will be?">
        <p>
          Pradeep Pandey studies this question at the University of
          Wisconsin–Stout under the supervision of Dr. Augustine Twumasi. Each
          method uses information available after the SPY market close to
          predict the sample standard deviation of the next five sessions’ daily
          log returns.
        </p>
        <p>
          Simple trailing volatility estimates give the model a meaningful test.
          A useful forecasting method should improve on those estimates across
          changing market conditions.
        </p>
        <div className="actions">
          <a href={repo}>
            <Github size={16} /> Repository
          </a>
          <a href={repo + "/blob/main/docs/protocols/prospective_protocol.md"}>
            <BookOpen size={16} /> Frozen protocol
          </a>
        </div>
      </Panel>
      <Milestones />
      <div className="two">
        <Panel title="From prices to publication">
          <p>
            Python, pandas and scikit-learn power the research. The collector
            follows the NYSE schedule, verifies the frozen model, archives
            adjusted-close vintages and records attempts in an append-only
            SQLite journal.
          </p>
          <p>
            A separate Python exporter verifies approved records. React,
            TypeScript and Recharts present the resulting public JSON. The
            static application supports GitHub Pages.
          </p>
        </Panel>
        <Panel title="Limitations and next steps">
          <p>
            Historical observations share returns across windows. Data
            revisions, past model selection and spikes in volatility limit what
            the historical comparison establishes. The five-session benchmark
            remains competitive.
          </p>
          <p>
            The next phase requires verified external timestamp retention and an
            active collector. A completed 2027 evaluation requires a separate
            approved release after the January 10, 2028 scoring boundary.
          </p>
          <Link to="/performance">Explore uncertainty and tail results</Link>
        </Panel>
      </div>
      <p className="notice">
        This website is for academic research and educational purposes. It does
        not provide investment advice or predict the direction of SPY prices.
      </p>
    </div>
  );
}
