import React, { Suspense, lazy, useEffect } from 'react'
import ReactDOM from 'react-dom/client'
import { MutationCache, QueryCache, QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom'
import { ApiError } from './lib/api'
import { LocaleProvider } from './lib/i18n'
import { ThemeProvider } from './lib/theme'
import { AuthGate } from './components/auth'
import { Layout } from './components/layout'
import { ErrorBoundary } from './components/error-boundary'
import './styles.css'

const Overview = lazy(() => import('./pages/overview'))
const Accounts = lazy(() => import('./pages/accounts'))
const Transactions = lazy(() => import('./pages/transactions'))
const Imports = lazy(() => import('./pages/imports'))
const Buckets = lazy(() => import('./pages/buckets'))
const Contracts = lazy(() => import('./pages/contracts'))
const Wishlist = lazy(() => import('./pages/wishlist'))
const Plan = lazy(() => import('./pages/plan'))
const Business = lazy(() => import('./pages/business'))
const Analysis = lazy(() => import('./pages/analysis'))
const NetWorth = lazy(() => import('./pages/networth'))
const Insights = lazy(() => import('./pages/insights'))
const Settings = lazy(() => import('./pages/settings'))
const Mcp = lazy(() => import('./pages/mcp'))
const McpAuthorize = lazy(() => import('./pages/mcp-authorize'))
const client = new QueryClient({
  mutationCache: new MutationCache({ onError: error => { if (error instanceof ApiError && error.status === 401) client.invalidateQueries({ queryKey: ['session'] }) } }),
  queryCache: new QueryCache({ onError: (error, query) => { if (error instanceof ApiError && error.status === 401 && query.queryKey[0] !== 'session') client.invalidateQueries({ queryKey: ['session'] }) } }),
  defaultOptions: { queries: { staleTime: 20_000, retry: (count, error) => count < 1 && !(error instanceof ApiError && error.status < 500), refetchOnWindowFocus: true }, mutations: { retry: false } },
})
function App() {
  useEffect(() => { document.documentElement.lang = localStorage.getItem('finsight-language') === 'en' ? 'en' : 'de' }, [])
  return <QueryClientProvider client={client}><LocaleProvider><ThemeProvider><BrowserRouter><AuthGate><Suspense fallback={<div className="state" role="status">FinSight …</div>}><Routes><Route element={<Layout />}><Route index element={<Overview />} /><Route path="accounts" element={<Accounts />} /><Route path="transactions" element={<Transactions />} /><Route path="imports" element={<Imports />} /><Route path="buckets" element={<Buckets />} /><Route path="contracts" element={<Contracts />} /><Route path="wishlist" element={<Wishlist />} /><Route path="plan" element={<Plan />} /><Route path="business" element={<Business />} /><Route path="analysis" element={<Analysis />} /><Route path="net-worth" element={<NetWorth />} /><Route path="insights" element={<Insights />} /><Route path="settings" element={<Settings />} /><Route path="settings/mcp" element={<Mcp />} /><Route path="mcp/authorize" element={<McpAuthorize />} /><Route path="*" element={<Navigate to="/" replace />} /></Route></Routes></Suspense></AuthGate></BrowserRouter></ThemeProvider></LocaleProvider></QueryClientProvider>
}
ReactDOM.createRoot(document.getElementById('root')!).render(<React.StrictMode><ErrorBoundary><App /></ErrorBoundary></React.StrictMode>)
