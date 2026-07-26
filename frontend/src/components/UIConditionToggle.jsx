import './AdaptiveUI.css';

/**
 * Research instrumentation (RQ3): switches the interface between the three
 * experimental conditions. Persisted in localStorage by the parent.
 *
 *  - static:   no agreement information shown (control)
 *  - badge:    minimal adaptation — consensus/divided chip only
 *  - adaptive: full layout reconfiguration driven by agreement
 */
const CONDITIONS = [
  { id: 'static', label: 'Static', icon: '▤', title: 'Control: no agreement information' },
  { id: 'badge', label: 'Badge', icon: '◉', title: 'Minimal adaptation: consensus badge' },
  { id: 'adaptive', label: 'Adaptive', icon: '⇄', title: 'Full adaptation: layout reconfigures with agreement' },
];

export default function UIConditionToggle({ value, onChange, disabled }) {
  return (
    <div className="ui-condition-toggle" role="group" aria-label="Interface condition">
      <span className="ui-condition-caption">Interface</span>
      {CONDITIONS.map((cond) => (
        <button
          key={cond.id}
          type="button"
          className={`ui-condition-btn ${value === cond.id ? 'active' : ''}`}
          onClick={() => onChange(cond.id)}
          disabled={disabled}
          title={cond.title}
        >
          <span className="ui-condition-icon">{cond.icon}</span>
          <span className="ui-condition-label">{cond.label}</span>
        </button>
      ))}
    </div>
  );
}
