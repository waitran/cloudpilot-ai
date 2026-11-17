import { ArrowLeft, Bot, FlaskConical } from 'lucide-react';
import { Link } from 'react-router-dom';

const content = {
  lab: {
    title: 'Optimization Lab',
    subtitle: 'Test the idea. Protect the outcome.',
    description:
      'Compare a baseline with candidate configurations under the same load. Review measured SLOs before approving any changes.',
    stage: 'Stage 6 · Experiment validation',
    icon: FlaskConical,
  },
  agent: {
    title: 'AI Agent',
    subtitle: 'Your future copilot for a more efficient cloud.',
    description:
      'Describe your goals in plain language. The agent will help formalize requirements and explain validated findings. The model is not connected yet.',
    stage: 'Stage 5 · AI orchestration',
    icon: Bot,
  },
};

export function Planned({ page }: { page: keyof typeof content }) {
  const item = content[page];
  const Icon = item.icon;
  return (
    <>
      <div className="page-heading">
        <div>
          <div className="eyebrow">WORKSPACE</div>
          <h1>{item.title}</h1>
          <p>{item.subtitle}</p>
        </div>
        <span className="subtle-pill">PLANNED</span>
      </div>
      <section className="empty-panel">
        <div className="empty-orbit">
          <Icon size={36} strokeWidth={1.5} />
        </div>
        <span className="eyebrow">{item.stage}</span>
        <h2>A little further on the horizon.</h2>
        <p>{item.description}</p>
        <Link className="secondary-button" to="/">
          <ArrowLeft size={15} />
          Back to overview
        </Link>
      </section>
    </>
  );
}
