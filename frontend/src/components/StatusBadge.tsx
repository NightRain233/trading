import { memo } from 'react';
import { clsx, type ClassValue } from 'clsx';
import { twMerge } from 'tailwind-merge';
import { motion } from 'framer-motion';

function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

const trendColors: Record<string, string> = {
  '强势多头': 'bg-emerald-500/12 text-emerald-400 border-emerald-500/25 badge-glow-green',
  '回调多头': 'bg-emerald-500/8 text-emerald-500/80 border-emerald-500/15',
  '强势空头': 'bg-rose-500/12 text-rose-400 border-rose-500/25 badge-glow-red',
  '反弹空头': 'bg-rose-500/8 text-rose-500/80 border-rose-500/15',
  '潜在转空': 'bg-amber-500/12 text-amber-400 border-amber-500/25 badge-glow-amber',
  '潜在转多': 'bg-sky-500/12 text-sky-400 border-sky-500/25 badge-glow-sky',
  '震荡': 'bg-zinc-500/10 text-zinc-400 border-zinc-500/20',
};

const signalColors: Record<string, string> = {
  '强烈信号': 'bg-violet-500/15 text-violet-300 font-bold border-violet-500/30 badge-glow-violet',
  '谨慎信号': 'bg-amber-500/12 text-amber-400 border-amber-500/25 badge-glow-amber',
  '观望': 'bg-zinc-800/40 text-zinc-600 border-zinc-700/40',
  'WAIT': 'bg-zinc-800/40 text-zinc-700 border-zinc-700/40 animate-pulse',
};

const glowColors: Record<string, string> = {
  '强烈信号': 'rgba(139,92,246,0.25)',
  '强势多头': 'rgba(16,185,129,0.25)',
  '强势空头': 'rgba(244,63,94,0.25)',
};

const dotColors: Record<string, string> = {
  '强烈信号': '#a78bfa',
  '强势多头': '#10b981',
  '强势空头': '#f43f5e',
};

const highPriorityAnimation = (status: string) => ({
  animate: {
    opacity: 1,
    scale: 1,
    boxShadow: [
      "0 0 12px -4px rgba(0,0,0,0)",
      `0 0 16px -3px ${glowColors[status]}`,
      "0 0 12px -4px rgba(0,0,0,0)"
    ],
  },
  transition: {
    duration: 0.3,
    boxShadow: { duration: 2.5, repeat: Infinity, ease: "easeInOut" },
  },
});

const normalAnimation = {
  animate: { opacity: 1, scale: 1 },
  transition: { duration: 0.3 },
};

interface StatusBadgeProps {
  status: string;
  type?: 'trend' | 'signal' | 'rsi';
}

export const StatusBadge = memo(function StatusBadge({ status, type = 'trend' }: StatusBadgeProps) {
  let colorClass = 'bg-zinc-800/40 text-zinc-500 border-zinc-700/40';

  if (type === 'trend') {
    colorClass = trendColors[status] || colorClass;
  } else if (type === 'signal') {
    colorClass = signalColors[status] || colorClass;
  } else {
    colorClass = trendColors[status] || signalColors[status] || colorClass;
  }

  const isHighPriority = status === '强烈信号' || status === '强势多头' || status === '强势空头';

  const anim = isHighPriority ? highPriorityAnimation(status) : normalAnimation;

  return (
    <motion.span
      initial={{ opacity: 0, scale: 0.9 }}
      animate={anim.animate}
      transition={anim.transition}
      className={cn(
        "px-2.5 py-0.5 rounded-lg text-[10px] sm:text-xs font-semibold border transition-colors whitespace-nowrap inline-flex items-center",
        colorClass
      )}
    >
      {isHighPriority && (
        <span className="w-1.5 h-1.5 rounded-full mr-1.5 animate-pulse" style={{ backgroundColor: dotColors[status] }} />
      )}
      {status}
    </motion.span>
  );
});
