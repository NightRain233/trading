import { useEffect, useState } from 'react';

/** Colours for lightweight-charts, read from the design tokens of the active theme. */
export interface ChartTheme {
  text: string;
  grid: string;
  border: string;
  rise: string;
  fall: string;
  accent: string;
  warn: string;
  ink: string;
  muted: string;
}

function readTheme(): ChartTheme {
  const style = getComputedStyle(document.documentElement);
  const v = (name: string) => style.getPropertyValue(name).trim();
  return {
    text: v('--ui-ink-3'),
    grid: v('--ui-line'),
    border: v('--ui-line'),
    rise: v('--ui-rise'),
    fall: v('--ui-fall'),
    accent: v('--ui-accent'),
    warn: v('--ui-warn'),
    ink: v('--ui-ink'),
    muted: v('--ui-ink-3'),
  };
}

/** Hex colour with an alpha suffix, e.g. for translucent volume bars. */
export const withAlpha = (hex: string, alpha: number) =>
  /^#[0-9a-f]{6}$/i.test(hex) ? `${hex}${Math.round(alpha * 255).toString(16).padStart(2, '0')}` : hex;

/** Current chart colours; changes when the theme toggle or the system setting flips. */
export function useChartTheme(): ChartTheme {
  const [theme, setTheme] = useState<ChartTheme>(readTheme);
  useEffect(() => {
    const update = () => setTheme(readTheme());
    const observer = new MutationObserver(update);
    observer.observe(document.documentElement, { attributes: true, attributeFilter: ['data-theme'] });
    const media = window.matchMedia('(prefers-color-scheme: light)');
    media.addEventListener('change', update);
    return () => { observer.disconnect(); media.removeEventListener('change', update); };
  }, []);
  return theme;
}
