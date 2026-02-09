import React from 'react';

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
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm">
      <div className="bg-zinc-900 border border-zinc-700 rounded-xl p-6 w-80">
        <h3 className="text-lg font-bold mb-4">创建新分组</h3>
        <input 
          type="text" 
          placeholder="分组名称..." 
          value={newGroupName}
          onChange={e => setNewGroupName(e.target.value)}
          className="w-full bg-zinc-800 border border-zinc-700 rounded-lg px-3 py-2 mb-4 focus:outline-none focus:border-emerald-500/50"
          autoFocus
        />
        <div className="flex gap-2 justify-end">
          <button 
            onClick={() => setShowNewGroupInput(false)}
            className="px-4 py-2 text-sm text-zinc-400 hover:text-white"
          >
            取消
          </button>
          <button 
            onClick={handleCreateGroup}
            className="px-4 py-2 text-sm bg-emerald-600 hover:bg-emerald-500 text-white rounded-lg"
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
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm">
      <div className="bg-zinc-900 border border-zinc-700 rounded-xl p-6 w-80">
        <h3 className="text-lg font-bold mb-4">Edit Alias ({symbol})</h3>
        <input 
          type="text" 
          placeholder="Enter alias..." 
          value={aliasInput}
          onChange={e => setAliasInput(e.target.value)}
          className="w-full bg-zinc-800 border border-zinc-700 rounded-lg px-3 py-2 mb-4 focus:outline-none focus:border-emerald-500/50"
          autoFocus
          onKeyDown={e => e.key === 'Enter' && handleEditAlias()}
        />
        <div className="flex gap-2 justify-end">
          <button 
            onClick={() => setAliasModalOpen(false)}
            className="px-4 py-2 text-sm text-zinc-400 hover:text-white"
          >
            Cancel
          </button>
          <button 
            onClick={handleEditAlias}
            className="px-4 py-2 text-sm bg-emerald-600 hover:bg-emerald-500 text-white rounded-lg"
          >
            Save
          </button>
        </div>
      </div>
    </div>
  );
};
