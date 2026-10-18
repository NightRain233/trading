import type { WeinsteinView } from '../types';
import { STAGE_HINTS, STAGE_NAMES } from '../marketView.js';

/** Only what is worth noticing this week: a Bollinger event or heavy volume. */
export function Signals({ view }: { view?: WeinsteinView | null }) {
  if (!view) return null;
  const items: Array<[string, string]> = [];
  if (view.bbState === 'squeeze_breakout') items.push(['warn', '收窄后突破']);
  else if (view.bbState === 'squeeze') items.push(['s1', '布林收窄']);
  else if (view.bbState === 'above_upper') items.push(['s2', '上轨之上']);
  if (view.volumeRatio != null && view.volumeRatio > 1.8) items.push(['ok', `放量 ${view.volumeRatio.toFixed(1)}`]);
  if (!items.length) return null;
  return <span className="ui-row" style={{ gap: 4, flexWrap: 'nowrap' }}>{items.map(([kind, text]) => <span key={text} className={`ui-chip ${kind}`}>{text}</span>)}</span>;
}

export function StageChip({ view, compact }: { view?: Pick<WeinsteinView, 'stage'> | null; compact?: boolean }) {
  if (!view) return <span className="ui-muted">—</span>;
  return (
    <span className={`ui-chip s${view.stage}`}>
      <i />{compact ? STAGE_HINTS[view.stage] : `${STAGE_NAMES[view.stage]}·${STAGE_HINTS[view.stage]}`}
    </span>
  );
}
