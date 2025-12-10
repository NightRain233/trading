import { clsx, type ClassValue } from 'clsx';
import { twMerge } from 'tailwind-merge';

function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

interface StatusBadgeProps {
  trend: string;
  adx: number;
}

export function StatusBadge({ trend, adx }: StatusBadgeProps) {
  // 根据趋势类型确定颜色
  const isStrongBullish = trend === '强势多头';
  const isPullbackBullish = trend === '回调多头';
  const isStrongBearish = trend === '强势空头';
  const isRebounceBearish = trend === '反弹空头';
  const isTransitioning = trend.includes('潜在转');
  const isRanging = trend === '震荡';

  return (
    <div className="flex items-center gap-2">
      <span
        className={cn(
          "px-2 py-0.5 rounded text-xs font-medium",
          isStrongBullish && "bg-emerald-600/20 text-emerald-300 font-bold border border-emerald-500/30",
          isPullbackBullish && "bg-emerald-600/10 text-emerald-400 border border-emerald-500/20",
          isStrongBearish && "bg-rose-600/20 text-rose-300 font-bold border border-rose-500/30",
          isRebounceBearish && "bg-rose-600/10 text-rose-400 border border-rose-500/20",
          isTransitioning && "bg-yellow-600/10 text-yellow-400 border border-yellow-500/20",
          isRanging && "bg-zinc-600/10 text-zinc-400 border border-zinc-500/20"
        )}
      >
        {trend}
      </span>
    </div>
  );
}
