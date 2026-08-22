// LumaFlow v1.0 (2026-08-07)
// Point d'entrée Vite/React : monte <App /> dans #root en StrictMode.
import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import App from './App.tsx'

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <App />
  </StrictMode>,
)
