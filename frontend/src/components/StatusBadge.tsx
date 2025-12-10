import { clsx, type ClassValue } from 'clsx';
import { twMerge } from 'tailwind-merge';

function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

interface StatusBadgeProps {
  trend: 'LONG' | 'SHORT' | 'NEUTRAL';
  strength: 'STRONG' | 'WEAK';
  adx: number;
}

export function StatusBadge({ trend, strength, adx }: StatusBadgeProps) {
  return (
    <div className="flex items-center gap-2">
      <span
        className={cn(
          "px-2.5 py-0.5 rounded-full text-xs font-medium border uppercase tracking-wider",
          trend === 'LONG' && "bg-emerald-500/10 text-emerald-400 border-emerald-500/20",
          trend === 'SHORT' && "bg-rose-500/10 text-rose-400 border-rose-500/20",
          trend === 'NEUTRAL' && "bg-zinc-500/10 text-zinc-400 border-zinc-500/20"
        )}
      >
        {trend}
      </span>
      
      {trend !== 'NEUTRAL' && (
        <span
          className={cn(
            "text-xs font-mono sm:hidden", // Hidden on small screens (desktop view where column exists)
            strength === 'STRONG' ? "text-yellow-400 font-bold" : "text-zinc-500"
          )}
          title={`ADX: ${adx.toFixed(2)}`}
        >
          ADX {adx.toFixed(2)}
        </span>
      )}
    </div>
  );
}
