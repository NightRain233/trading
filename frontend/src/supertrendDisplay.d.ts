export type SupertrendDisplaySignal = {
  key: 'fresh_bull' | 'pullback_buy' | 'pre_bull' | 'risk';
  label: string;
  tone: 'emerald' | 'cyan' | 'amber' | 'red';
  rank: number;
};

export const DISPLAY_SIGNAL_TONES: Record<SupertrendDisplaySignal['tone'], string>;

export function deriveDisplaySignal<T extends {
  state?: string | null;
  weeklyState?: string | null;
  justFlipped?: boolean | null;
  alertType?: string | null;
}>(item: T): SupertrendDisplaySignal | null;

export function getWeakOpportunityHint<T extends {
  state?: string | null;
  opportunityStage?: string | null;
  distanceToSupertrendAtr?: number | null;
}>(item: T): string | null;

export function isDefaultVisible<T extends {
  state?: string | null;
  weeklyState?: string | null;
  justFlipped?: boolean | null;
  alertType?: string | null;
  alertPriority?: string | null;
}>(item: T, mark?: string): boolean;

export function sortSupertrendItems<T extends {
  symbol?: string | null;
  state?: string | null;
  weeklyState?: string | null;
  justFlipped?: boolean | null;
  alertType?: string | null;
  alertPriority?: string | null;
  distanceToSupertrendAtr?: number | null;
  distanceToSupertrendPct?: number | null;
}>(items: T[], marks?: Record<string, string | undefined>): T[];

export function deriveConfluenceLabel<T extends {
  state?: string | null;
  weeklyState?: string | null;
}>(item: T): string;
