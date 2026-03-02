import React from 'react';
import { X, FolderPlus, Pencil } from 'lucide-react';

interface NewGroupModalProps {
  newGroupName: string;
  setNewGroupName: (val: string) => void;
  handleCreateGroup: () => void;
  setShowNewGroupInput: (val: boolean) => void;
}

export const NewGroupModal: React.FC<NewGroupModalProps> = ({
  newGroupName,
  setNewGroupName,
  handleCreateGroup,
  setShowNewGroupInput,
}) => {
  return (
    <div className="modal-overlay fixed inset-0 z-50 flex items-center justify-center animate-fade-in-scale">
      <div className="glass-card rounded-2xl p-6 w-80 shadow-2xl animate-fade-in-up">
        <div className="flex items-center gap-2.5 mb-5">
          <div className="bg-emerald-500/10 p-2 rounded-xl border border-emerald-500/20">
            <FolderPlus size={18} className="text-emerald-400" />
          </div>
          <h3 className="text-lg font-bold text-zinc-100">创建新分组</h3>
        </div>
        <input
          type="text"
          placeholder="输入分组名称..."
          value={newGroupName}
          onChange={e => setNewGroupName(e.target.value)}
          className="w-full input-glass rounded-xl px-4 py-2.5 mb-5 focus:outline-none text-sm placeholder:text-zinc-600"
          autoFocus
          onKeyDown={e => e.key === 'Enter' && handleCreateGroup()}
        />
        <div className="flex gap-2 justify-end">
          <button
            onClick={() => setShowNewGroupInput(false)}
            className="px-4 py-2 text-sm text-zinc-500 hover:text-zinc-300 rounded-xl hover:bg-zinc-800/50 transition-all duration-200"
          >
            取消
          </button>
          <button
            onClick={handleCreateGroup}
            className="px-4 py-2 text-sm bg-gradient-to-r from-emerald-600 to-emerald-500 hover:from-emerald-500 hover:to-emerald-400 text-white rounded-xl font-semibold transition-all duration-200 shadow-[0_0_20px_-5px_rgba(16,185,129,0.3)] hover:shadow-[0_0_25px_-5px_rgba(16,185,129,0.4)]"
          >
            创建
          </button>
        </div>
      </div>
    </div>
  );
};

interface AliasEditModalProps {
  symbol: string;
  aliasInput: string;
  setAliasInput: (val: string) => void;
  handleEditAlias: () => void;
  setAliasModalOpen: (val: boolean) => void;
}

export const AliasEditModal: React.FC<AliasEditModalProps> = ({
  symbol,
  aliasInput,
  setAliasInput,
  handleEditAlias,
  setAliasModalOpen,
}) => {
  return (
    <div className="modal-overlay fixed inset-0 z-50 flex items-center justify-center animate-fade-in-scale">
      <div className="glass-card rounded-2xl p-6 w-80 shadow-2xl animate-fade-in-up">
        <div className="flex items-center justify-between mb-5">
          <div className="flex items-center gap-2.5">
            <div className="bg-sky-500/10 p-2 rounded-xl border border-sky-500/20">
              <Pencil size={16} className="text-sky-400" />
            </div>
            <div>
              <h3 className="text-base font-bold text-zinc-100">编辑别名</h3>
              <span className="text-[10px] text-zinc-500 font-mono">{symbol}</span>
            </div>
          </div>
          <button
            onClick={() => setAliasModalOpen(false)}
            className="p-1.5 text-zinc-600 hover:text-zinc-300 hover:bg-zinc-800/50 rounded-lg transition-all"
          >
            <X size={16} />
          </button>
        </div>
        <input
          type="text"
          placeholder="输入别名..."
          value={aliasInput}
          onChange={e => setAliasInput(e.target.value)}
          className="w-full input-glass rounded-xl px-4 py-2.5 mb-5 focus:outline-none text-sm placeholder:text-zinc-600"
          autoFocus
          onKeyDown={e => e.key === 'Enter' && handleEditAlias()}
        />
        <div className="flex gap-2 justify-end">
          <button
            onClick={() => setAliasModalOpen(false)}
            className="px-4 py-2 text-sm text-zinc-500 hover:text-zinc-300 rounded-xl hover:bg-zinc-800/50 transition-all duration-200"
          >
            取消
          </button>
          <button
            onClick={handleEditAlias}
            className="px-4 py-2 text-sm bg-gradient-to-r from-sky-600 to-sky-500 hover:from-sky-500 hover:to-sky-400 text-white rounded-xl font-semibold transition-all duration-200 shadow-[0_0_20px_-5px_rgba(14,165,233,0.3)] hover:shadow-[0_0_25px_-5px_rgba(14,165,233,0.4)]"
          >
            保存
          </button>
        </div>
      </div>
    </div>
  );
};
