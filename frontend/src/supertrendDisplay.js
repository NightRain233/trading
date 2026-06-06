export const DISPLAY_SIGNAL_TONES = {
  emerald: 'text-emerald-200 border-emerald-500/35 bg-emerald-500/10',
  cyan: 'text-cyan-200 border-cyan-500/35 bg-cyan-500/10',
  amber: 'text-amber-200 border-amber-500/35 bg-amber-500/10',
  red: 'text-red-200 border-red-500/35 bg-red-500/10',
};

const PINNED_MARKS = new Set(['watch', 'holding']);

function isWeeklyBull(item) {
  return item.weeklyState === 'bull' || item.weeklyState === 'bull_flip';
}

function isDailyBull(item) {
  return item.state === 'bull' || item.state === 'bull_flip';
}

function isDailyBear(item) {
  return item.state === 'bear' || item.state === 'bear_flip';
}

function isDailyBullFlip(item) {
  return item.state === 'bull_flip' || (Boolean(item.justFlipped) && isDailyBull(item));
}

function isDailyBearFlip(item) {
  return item.state === 'bear_flip' || (Boolean(item.justFlipped) && isDailyBear(item));
}

export function deriveDisplaySignal(item) {
  if (isWeeklyBull(item) && isDailyBullFlip(item)) {
    return { key: 'fresh_bull', label: '刚翻多', tone: 'emerald', rank: 0 };
  }
  if (isDailyBull(item) && item.alertType === 'support_test') {
    return { key: 'pullback_buy', label: '回踩买点', tone: 'cyan', rank: 1 };
  }
  if (isWeeklyBull(item) && isDailyBear(item) && item.alertType === 'resistance_test') {
    return { key: 'pre_bull', label: '预备翻多', tone: 'amber', rank: 2 };
  }
  if (item.alertType === 'sell_or_risk' || isDailyBearFlip(item)) {
    return { key: 'risk', label: '风控', tone: 'red', rank: 3 };
  }
  return null;
}

export function getWeakOpportunityHint(item) {
  if (!isDailyBull(item)) return null;
  if (item.opportunityStage !== 'wait_pullback' && item.opportunityStage !== 'extended_from_entry') return null;
  const atr = Number(item.distanceToSupertrendAtr);
  if (!Number.isFinite(atr)) return '等回踩';
  return `离支撑 ${atr.toFixed(2)} ATR，等回踩`;
}

export function isDefaultVisible(item, mark = 'none') {
  if (deriveDisplaySignal(item)) return true;
  return PINNED_MARKS.has(mark) && item.alertPriority === 'high';
}

function markedHighRank(item, mark) {
  return PINNED_MARKS.has(mark) && item.alertPriority === 'high' ? 4 : 5;
}

export function sortSupertrendItems(items, marks = {}) {
  return [...items].sort((a, b) => {
    const aSignal = deriveDisplaySignal(a);
    const bSignal = deriveDisplaySignal(b);
    const aRank = aSignal ? aSignal.rank : markedHighRank(a, marks[a.symbol]);
    const bRank = bSignal ? bSignal.rank : markedHighRank(b, marks[b.symbol]);
    if (aRank !== bRank) return aRank - bRank;

    const aDistance = Number(a.distanceToSupertrendAtr ?? a.distanceToSupertrendPct ?? Number.POSITIVE_INFINITY);
    const bDistance = Number(b.distanceToSupertrendAtr ?? b.distanceToSupertrendPct ?? Number.POSITIVE_INFINITY);
    if (Number.isFinite(aDistance) && Number.isFinite(bDistance) && aDistance !== bDistance) {
      return aDistance - bDistance;
    }

    return String(a.symbol || '').localeCompare(String(b.symbol || ''));
  });
}

const WEEKLY_LABELS = {
  bull: '周多',
  bull_flip: '周刚多',
  bear: '周空',
  bear_flip: '周刚空',
};

const DAILY_LABELS = {
  bull: '日多',
  bull_flip: '日刚多',
  bear: '日空',
  bear_flip: '日刚空',
};

export function deriveConfluenceLabel(item) {
  const parts = [];
  if (item.weeklyState && WEEKLY_LABELS[item.weeklyState]) {
    parts.push(WEEKLY_LABELS[item.weeklyState]);
  }
  if (item.state && DAILY_LABELS[item.state]) {
    parts.push(DAILY_LABELS[item.state]);
  }
  return parts.join(' · ');
}
