import { useEffect, useRef, useState } from 'react'
import { NavLink, Outlet, useLocation } from 'react-router-dom'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { ArrowDownToLine, ArrowLeftRight, Bell, ChevronRight, LayoutDashboard, LogOut, Menu, Moon, PiggyBank, Settings, ShieldCheck, Sparkles, Sun, Wallet, X, FileText, Gift, BarChart3, Landmark, Target, Briefcase, Receipt, FileBarChart, Sigma } from 'lucide-react'
import { send } from '../lib/api'
import { useLocale, type TranslationKey } from '../lib/i18n'
import { Brand } from './auth'
import { Button, Feedback } from './ui'
import { useTheme } from '../lib/theme'

const navigation = [
  { key: 'overview', path: '/', icon: LayoutDashboard }, { key: 'accounts', path: '/accounts', icon: Wallet },
  { key: 'transactions', path: '/transactions', icon: ArrowLeftRight }, { key: 'buckets', path: '/buckets', icon: PiggyBank }, { key: 'plan', path: '/plan', icon: Target }, { key: 'receipts', path: '/receipts', icon: Receipt },
  { key: 'contracts', path: '/contracts', icon: FileText }, { key: 'analysis', path: '/analysis', icon: BarChart3 }, { key: 'averages', path: '/averages', icon: Sigma }, { key: 'report', path: '/report', icon: FileBarChart }, { key: 'networth', path: '/net-worth', icon: Landmark }, { key: 'wishlist', path: '/wishlist', icon: Gift }, { key: 'business', path: '/business', icon: Briefcase }, { key: 'imports', path: '/imports', icon: ArrowDownToLine },
] as const
export function Layout() {
  const { t, language, setLanguage } = useLocale()
  const { dark, toggle } = useTheme()
  const [open, setOpen] = useState(false)
  const sidebar = useRef<HTMLElement>(null)
  const location = useLocation()
  const client = useQueryClient()
  const logout = useMutation({ mutationFn: () => send('/auth/logout'), onSuccess: () => { client.clear(); window.location.assign('/') } })
   const title = [...navigation, { key: 'insights', path: '/insights' }, { key: 'settings', path: '/settings' }, { key: 'settings', path: '/settings/mcp' }, { key: 'settings', path: '/mcp/authorize' }].find(n => n.path === location.pathname)?.key || 'overview'
  useEffect(() => {
    if (!open) return
    const previous = document.activeElement as HTMLElement
    const overflow = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    sidebar.current?.querySelector<HTMLElement>('button, a')?.focus()
    const keyboard = (event: KeyboardEvent) => {
      if (event.key === 'Escape') { event.preventDefault(); setOpen(false) }
      if (event.key === 'Tab') {
        const nodes = [...(sidebar.current?.querySelectorAll<HTMLElement>('a[href], button:not(:disabled)') || [])].filter(el => el.getClientRects().length)
        const first = nodes[0], last = nodes[nodes.length - 1]
        if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last?.focus() }
        else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first?.focus() }
      }
    }
    document.addEventListener('keydown', keyboard)
    return () => { document.body.style.overflow = overflow; document.removeEventListener('keydown', keyboard); previous?.focus() }
  }, [open])
  return <div className="app-shell">
    <a className="skip-link" href="#main">{t('skip')}</a>
    {open && <div className="sidebar-backdrop" onClick={() => setOpen(false)} />}
    <aside ref={sidebar} className={`sidebar ${open ? 'is-open' : ''}`} id="navigation-sidebar">
      <div className="sidebar-brand"><Brand /><Button className="mobile-only" variant="ghost" aria-label={t('close')} onClick={() => setOpen(false)}><X size={20} /></Button></div>
      <div className="workspace-label">PERSONAL WORKSPACE <span>01</span></div>
      <nav aria-label={t('workspace')}>
        <p className="nav-label">{t('workspace')}</p>
        {navigation.map(({ key, path, icon: Icon }) => <NavLink end={path === '/'} key={path} to={path} onClick={() => setOpen(false)} className={({ isActive }) => `nav-item ${isActive ? 'active' : ''}`}><Icon size={19} /><span>{t(key)}</span>{key === 'overview' && <span className="nav-active-dot" />}</NavLink>)}
        <p className="nav-label second">{t('intelligence')}</p>
        <NavLink to="/insights" className="nav-item" onClick={() => setOpen(false)}><Sparkles size={19} /><span>{t('insights')}</span><span className="small-ai">AI</span></NavLink>
      </nav>
      <div className="sidebar-bottom">
        <div className="privacy-card"><ShieldCheck size={20} /><strong>{t('private')}</strong><p>{t('privateText')}</p></div>
        <NavLink to="/settings" className="nav-item" onClick={() => setOpen(false)}><Settings size={18} />{t('settings')}</NavLink>
        <Button variant="ghost" onClick={() => logout.mutate()} busy={logout.isPending}><LogOut size={18} />{t('logout')}</Button>
        <Feedback error={logout.error} />
        <div className="sidebar-footer"><span>FinSight</span><span>v0.1 · self-hosted</span></div>
      </div>
    </aside>
    <div className="main-shell">
      <header className="topbar">
        <div className="breadcrumb"><Button className="mobile-only" variant="ghost" onClick={() => setOpen(true)} aria-label={t('openMenu')} aria-expanded={open} aria-controls="navigation-sidebar"><Menu size={22} /></Button><span className="desktop-only">Workspace</span><ChevronRight size={14} className="desktop-only" /><strong>{t(title as TranslationKey)}</strong></div>
        <div className="topbar-actions">
          <span className="local-indicator"><span /> {language === 'de' ? 'Lokal & privat' : 'Local & private'}</span>
          <button className="locale-button" onClick={() => setLanguage(language === 'de' ? 'en' : 'de')} aria-label={t('language')}>{language.toUpperCase()}</button>
          <Button variant="ghost" onClick={toggle} aria-label={dark ? t('light') : t('dark')}>{dark ? <Sun size={18} /> : <Moon size={18} />}</Button>
          <NavLink className="icon-link" to="/settings" aria-label={t('notifications')}><Bell size={18} /></NavLink><span className="avatar" aria-label="Owner">F</span>
        </div>
      </header>
      <main id="main" className="main-content" tabIndex={-1} key={location.pathname}><Outlet /></main>
      <footer className="main-footer"><span>FinSight — Your money. Clearer insights.</span><span>Self-hosted · No telemetry</span></footer>
    </div>
  </div>
}
