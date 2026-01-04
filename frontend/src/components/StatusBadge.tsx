import { clsx, type ClassValue } from 'clsx';
import { twMerge } from 'tailwind-merge';

function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

interface StatusBadgeProps {
  status: string;
  type?: 'trend' | 'signal' | 'rsi';
}

export function StatusBadge({ status, type = 'trend' }: StatusBadgeProps) {
  // 趋势派色
  const trendColors: Record<string, string> = {
    '强势多头': 'bg-emerald-600/20 text-emerald-300 font-bold border-emerald-500/30',
    '回调多头': 'bg-emerald-600/10 text-emerald-400 border-emerald-500/20',
    '强势空头': 'bg-rose-600/20 text-rose-300 font-bold border-rose-500/30',
    '反弹空头': 'bg-rose-600/10 text-rose-400 border-rose-500/20',
    '潜在转空': 'bg-yellow-600/10 text-yellow-400 border-yellow-500/20',
    '潜在转多': 'bg-blue-600/10 text-blue-400 border-blue-500/20',
    '震荡': 'bg-zinc-600/10 text-zinc-400 border-zinc-500/20',
  };

  // 信号派色
  const signalColors: Record<string, string> = {
    '强烈信号': 'bg-purple-600/20 text-purple-300 font-bold border-purple-500/30',
    '谨慎信号': 'bg-zinc-800 text-zinc-300 border-zinc-700',
    '观望': 'bg-zinc-900 text-zinc-500 border-zinc-800',
    'WAIT': 'bg-zinc-900 text-zinc-600 border-zinc-800 animate-pulse',
  };

  let colorClass = 'bg-zinc-800 text-zinc-400 border-zinc-700';
  
  if (type === 'trend') {
    colorClass = trendColors[status] || colorClass;
  } else if (type === 'signal') {
    colorClass = signalColors[status] || colorClass;
  } else {
    colorClass = trendColors[status] || signalColors[status] || colorClass;
  }

  return (
    <span
      className={cn(
        "px-2 py-0.5 rounded text-[10px] sm:text-xs font-medium border transition-all",
        colorClass
      )}
    >
      {status}
    </span>
  );
}
