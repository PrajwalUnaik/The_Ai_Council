import { getShortModelName } from '../utils/modelHelpers';
import './AdaptiveUI.css';

/**
 * Research instrumentation (RQ2/RQ3): visual communication of inter-model
 * agreement computed by the backend (metadata.agreement).
 *
 * - <ConsensusBadge>   minimal adaptation — a small chip, layout unchanged
 * - <ConfidenceScore>  full adaptation, consensus state — prominent score
 * - <DividedBanner>    full adaptation, divided state — explicit warning
 */

function pct(value) {
  if (value === null || value === undefined) return '—';
  return `${Math.round(value * 100)}%`;
}

export default function ConsensusBadge({ agreement }) {
  if (!agreement || !agreement.council_state) return null;
  const isConsensus = agreement.council_state === 'consensus';

  return (
    <div
      className={`consensus-badge ${isConsensus ? 'consensus' : 'divided'}`}
      title={`Top-pick agreement: ${pct(agreement.top1_agreement)} · Kendall's W: ${agreement.kendalls_w ?? '—'} · ${agreement.n_rankers} rankers`}
    >
      <span className="consensus-badge-dot" />
      <span className="consensus-badge-label">
        {isConsensus ? 'High Consensus' : 'Council Divided'}
      </span>
      <span className="consensus-badge-value">{pct(agreement.top1_agreement)}</span>
    </div>
  );
}

export function ConfidenceScore({ agreement }) {
  if (!agreement) return null;
  return (
    <div className="confidence-score glass-panel">
      <div className="confidence-score-main">
        <span className="confidence-score-value">{pct(agreement.top1_agreement)}</span>
        <span className="confidence-score-caption">council agreement</span>
      </div>
      <div className="confidence-score-details">
        <div className="confidence-detail">
          <span className="confidence-detail-label">Preferred response</span>
          <span className="confidence-detail-value">
            {agreement.top1_model ? getShortModelName(agreement.top1_model) : '—'}
          </span>
        </div>
        <div className="confidence-detail">
          <span className="confidence-detail-label">Ranking concordance (W)</span>
          <span className="confidence-detail-value">
            {agreement.kendalls_w !== null && agreement.kendalls_w !== undefined
              ? agreement.kendalls_w.toFixed(2)
              : '—'}
          </span>
        </div>
        <div className="confidence-detail">
          <span className="confidence-detail-label">Rankers</span>
          <span className="confidence-detail-value">{agreement.n_rankers}</span>
        </div>
      </div>
    </div>
  );
}

export function DividedBanner({ agreement }) {
  if (!agreement) return null;
  const votes = agreement.top1_votes || {};
  const voteSummary = Object.entries(votes)
    .sort((a, b) => b[1] - a[1])
    .map(([label, count]) => `${label}: ${count}`)
    .join(' · ');

  return (
    <div className="divided-banner">
      <span className="divided-banner-icon">⚠️</span>
      <div className="divided-banner-body">
        <div className="divided-banner-title">The council was divided on this answer</div>
        <div className="divided-banner-text">
          Only {pct(agreement.top1_agreement)} of models agreed on the best response
          {voteSummary ? ` (${voteSummary})` : ''}. The individual responses are shown
          side-by-side below so you can compare them — the final answer attempts to
          balance the diverging views.
        </div>
      </div>
    </div>
  );
}
