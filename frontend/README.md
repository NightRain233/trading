# 前端

React 19 + TypeScript + Vite + Tailwind CSS 4。项目说明见 [../README.md](../README.md)，开发约定见 [../AGENTS.md](../AGENTS.md)。

```bash
pnpm install
pnpm dev                     # http://127.0.0.1:5173，/api 代理到 :8000
node --test test/*.mjs       # 纯函数助手的测试
pnpm build                   # 类型检查 + 打包
pnpm exec eslint src
```

- 页面组件在 `src/components/`，外壳与导航在 `AppShell.tsx`。
- 颜色、字号、间距统一用 `src/design.css` 里的 `--ui-*` 变量，浅色和深色各有一套；涨跌按 A 股习惯红涨绿跌。
- 计算和格式化放在 `src/*.js`（带 `// @ts-check` 和 `.d.ts`），用 `node --test` 测试，页面组件只负责展示。
