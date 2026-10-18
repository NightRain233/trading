import React, { useEffect, useState } from 'react';
import { BarChart3, BookOpen, Home, LineChart, MoreHorizontal, Waves } from 'lucide-react';

export type AppTab = 'watchlist' | 'rs' | 'wbb' | 'st' | 'history' | 'portfolio';

interface NavItem {
  tab: AppTab;
  label: string;
  hint: string;
  icon: React.ReactNode;
}

const ICON = { size: 20, strokeWidth: 1.6 } as const;

const MAIN_TABS: NavItem[] = [
  { tab: 'portfolio', label: '我的组合', hint: '每天看一眼', icon: <Home {...ICON} /> },
  { tab: 'watchlist', label: '看盘', hint: '自选与大盘', icon: <BarChart3 {...ICON} /> },
  { tab: 'wbb', label: '周线扫描', hint: '周末复盘用', icon: <Waves {...ICON} /> },
  { tab: 'history', label: '复盘', hint: '历史买卖点', icon: <BookOpen {...ICON} /> },
];

const MORE_TABS: NavItem[] = [
  { tab: 'st', label: 'SuperTrend', hint: '日线趋势扫描', icon: <LineChart {...ICON} /> },
  { tab: 'rs', label: 'RS 轮动', hint: '历史研究工具', icon: <LineChart {...ICON} /> },
];

type ThemeChoice = 'system' | 'light' | 'dark';
const THEMES: Array<[ThemeChoice, string]> = [['system', '跟随系统'], ['light', '浅色'], ['dark', '深色']];

function loadTheme(): ThemeChoice {
  try {
    const saved = localStorage.getItem('ui.theme');
    if (saved === 'light' || saved === 'dark') return saved;
  } catch { /* per-viewer preference only */ }
  return 'system';
}

function ThemeToggle({ theme, onChange }: { theme: ThemeChoice; onChange: (next: ThemeChoice) => void }) {
  return (
    <div className="ui-theme" role="group" aria-label="颜色主题">
      {THEMES.map(([value, label]) => (
        <button key={value} type="button" aria-pressed={theme === value} onClick={() => onChange(value)}>{label}</button>
      ))}
    </div>
  );
}

interface AppShellProps {
  activeTab: AppTab;
  onTabChange: (tab: AppTab) => void;
  children: React.ReactNode;
}

export const AppShell: React.FC<AppShellProps> = ({ activeTab, onTabChange, children }) => {
  const [moreOpen, setMoreOpen] = useState(false);
  const [theme, setTheme] = useState<ThemeChoice>(loadTheme);
  useEffect(() => {
    const root = document.documentElement;
    if (theme === 'system') root.removeAttribute('data-theme');
    else root.setAttribute('data-theme', theme);
    try {
      if (theme === 'system') localStorage.removeItem('ui.theme');
      else localStorage.setItem('ui.theme', theme);
    } catch { /* per-viewer preference only */ }
  }, [theme]);
  const inMore = MORE_TABS.some(item => item.tab === activeTab);
  const go = (tab: AppTab) => {
    setMoreOpen(false);
    onTabChange(tab);
  };

  const navButton = (item: NavItem) => (
    <button
      key={item.tab}
      type="button"
      onClick={() => go(item.tab)}
      aria-current={activeTab === item.tab ? 'page' : undefined}
    >
      {item.icon}
      <span>{item.label}<small>{item.hint}</small></span>
    </button>
  );

  return (
    <div className="ui-shell">
      <aside className="ui-rail" aria-label="主导航">
        <div className="ui-brand"><b>看盘台</b><span>三组合 + BTC 7.5%</span></div>
        <nav className="ui-nav">
          {MAIN_TABS.map(navButton)}
          <div className="ui-nav-sep">更多</div>
          {MORE_TABS.map(navButton)}
        </nav>
        <ThemeToggle theme={theme} onChange={setTheme} />
      </aside>

      <div className="ui-content">{children}</div>

      <div className="ui-more-sheet" hidden={!moreOpen} role="menu" aria-label="更多页面">
        {MORE_TABS.map(item => (
          <button key={item.tab} type="button" role="menuitem" onClick={() => go(item.tab)}>
            {item.label}<small>{item.hint}</small>
          </button>
        ))}
        <ThemeToggle theme={theme} onChange={setTheme} />
      </div>
      <nav className="ui-tabbar" aria-label="主导航">
        {MAIN_TABS.map(item => (
          <button
            key={item.tab}
            type="button"
            onClick={() => go(item.tab)}
            aria-current={activeTab === item.tab ? 'page' : undefined}
          >
            {item.icon}{item.label}
          </button>
        ))}
        <button
          type="button"
          onClick={() => setMoreOpen(open => !open)}
          aria-expanded={moreOpen}
          aria-current={inMore ? 'page' : undefined}
        >
          <MoreHorizontal {...ICON} />更多
        </button>
      </nav>
    </div>
  );
};
