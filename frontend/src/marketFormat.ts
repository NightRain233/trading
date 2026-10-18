/** Formatting shared by the market and weekly scan pages. */
export const signed = (value: number | null | undefined, digits = 1) =>
  value == null || !Number.isFinite(value) ? '—' : `${value > 0 ? '+' : ''}${(value * 100).toFixed(digits)}%`;
export const tone = (value: number | null | undefined) =>
  value == null || !Number.isFinite(value) || value === 0 ? '' : value > 0 ? 'ui-rise' : 'ui-fall';
export const stageColor = (stage: number | null | undefined) =>
  stage === 2 ? 'var(--ui-rise)' : stage === 4 ? 'var(--ui-fall)' : stage === 3 ? 'var(--ui-warn)' : 'var(--ui-flat)';
