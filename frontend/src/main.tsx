import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import App from './App.tsx'

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <App />
  </StrictMode>,
)

// 延迟注册 Service Worker，不阻塞首屏渲染和 API 请求
import('virtual:pwa-register').then(({ registerSW }) => {
  registerSW({ immediate: true })
})
