import { useEffect, useState } from 'react';
import { X } from 'lucide-react';

interface PresetHoldings {
  label: string;
  holdings: string[];
  date: string | null;
}

interface Props { onClose: () => void; }

export function RsHoldingsPanel({ onClose }: Props) {
  const [data, setData] = useState<Record<string, PresetHoldings> | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    fetch('/api/rs-rotation/holdings')
      .then(r => r.json())
      .then(setData)
      .finally(() => setLoading(false));
  }, []);

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-4">
      <div className="bg-slate-900 rounded-xl w-full max-w-md flex flex-col gap-4 p-5">
        <div className="flex items-center justify-between">
          <span className="text-white font-semibold text-lg">RS 轮动 · 当前持仓</span>
          <button onClick={onClose} className="text-slate-400 hover:text-white"><X size={20} /></button>
        </div>

        {loading && <div className="text-slate-400 text-sm">加载中…</div>}

        {data && Object.entries(data).map(([id, preset]) => (
          <div key={id} className="flex flex-col gap-2">
            <div className="text-xs text-slate-400">{preset.label}{preset.date ? `（${preset.date}）` : ''}</div>
            {preset.holdings.length === 0
              ? <div className="text-slate-500 text-sm">空仓</div>
              : <div className="flex flex-wrap gap-2">
                  {preset.holdings.map(s => (
                    <span key={s} className="bg-slate-800 text-amber-400 text-sm font-mono px-3 py-1 rounded-lg border border-slate-700">
                      {s}
                    </span>
                  ))}
                </div>
            }
          </div>
        ))}
      </div>
    </div>
  );
}
