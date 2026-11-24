import { useEffect, useRef, useState, type ReactNode, type FormEvent } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ArrowRight, ChartNoAxesCombined, LockKeyhole, ShieldCheck } from 'lucide-react'
import { api, ApiError, send } from '../lib/api'
import type { Session } from '../lib/types'
import { useLocale } from '../lib/i18n'
import { Button, Feedback, Field, QueryState } from './ui'

export function Brand() { return <div className="brand"><span className="brand-mark"><ChartNoAxesCombined size={24} strokeWidth={2.4} /></span><span>FinSight<span className="brand-dot">.</span></span></div> }
export function AuthGate({ children }: { children: ReactNode }) {
  const query = useQuery({ queryKey: ['session'], queryFn: async () => {
    const status = await api<Session>('/auth/status')
    if (status.authenticated) {
      try { await api('/auth/me') } catch (e) { if (e instanceof ApiError && e.status === 401) return { ...status, authenticated: false }; throw e }
    }
    return status
  }, retry: false, staleTime: 30_000 })
  if (query.isPending || query.error) return <div className="auth-page"><div className="auth-card"><Brand /><QueryState pending={query.isPending} error={query.error} retry={query.refetch}>{null}</QueryState></div></div>
  if (!query.data?.authenticated) return <AuthForm setup={query.data?.initialized === false || !!query.data?.setup_required} devLogin={!!query.data?.dev_login} />
  return <>{children}</>
}
function AuthForm({ setup, devLogin }: { setup: boolean; devLogin: boolean }) {
  const { t, language, setLanguage } = useLocale()
  const client = useQueryClient()
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [secret, setSecret] = useState('')
  const mutation = useMutation({
    mutationFn: () => send<Session>(setup ? '/auth/setup' : '/auth/login', { email, password, ...(setup ? { bootstrap_secret: secret } : {}) }),
    onSuccess: async () => { setPassword(''); setSecret(''); client.removeQueries({ predicate: q => q.queryKey[0] !== 'session' }); await client.invalidateQueries({ queryKey: ['session'] }) },
    onError: () => { setPassword(''); setSecret('') },
  })
  const submit = (e: FormEvent) => { e.preventDefault(); mutation.mutate() }
  const dev = useMutation({
    mutationFn: () => send<Session>('/auth/dev-login'),
    onSuccess: async () => { try { sessionStorage.removeItem('finsight.devLoginOff') } catch { /* storage blocked */ } client.removeQueries({ predicate: q => q.queryKey[0] !== 'session' }); await client.invalidateQueries({ queryKey: ['session'] }) },
  })
  const tried = useRef(false)
  useEffect(() => {
    if (!devLogin || setup || tried.current) return
    tried.current = true
    let off = false
    try { off = sessionStorage.getItem('finsight.devLoginOff') === '1' } catch { /* storage blocked */ }
    if (!off) dev.mutate()
  }, [devLogin, setup, dev])
  return <div className="auth-page">
    <div className="auth-story">
      <Brand />
      <div><span className="eyebrow">YOUR MONEY. CLEARER INSIGHTS.</span><h1>{language === 'de' ? <>Mehr Überblick.<br />Mehr du.</> : <>A clearer picture.<br />A calmer you.</>}</h1><p>{t('privateText')}</p></div>
      <span className="auth-privacy"><ShieldCheck size={18} /> {t('private')}</span>
    </div>
    <main className="auth-main">
      <button className="language-toggle" onClick={() => setLanguage(language === 'de' ? 'en' : 'de')}>{language === 'de' ? 'English' : 'Deutsch'}</button>
      <div className="auth-card">
        <span className="auth-lock"><LockKeyhole size={24} /></span><h1>{t(setup ? 'setup' : 'login')}</h1><p>{t(setup ? 'setupText' : 'loginText')}</p>
        {devLogin && !setup && <div className="form-stack">
          <Button type="button" busy={dev.isPending} onClick={() => dev.mutate()}>{language === 'de' ? 'Ohne Passwort anmelden' : 'Sign in without password'}<ArrowRight size={17} /></Button>
          <small className="muted">{language === 'de' ? 'Entwicklungsmodus: nur auf diesem Mac (localhost) aktiv.' : 'Development mode: only on this Mac (localhost).'}</small>
          <Feedback error={dev.error} />
        </div>}
        <form onSubmit={submit} className="form-stack">
          <Field label="E-Mail"><input type="email" value={email} onChange={e => setEmail(e.target.value)} autoComplete="username" required maxLength={254} autoFocus /></Field>
          <Field label={t('password')} hint={setup ? (language === 'de' ? 'Mindestens 12 Zeichen.' : 'At least 12 characters.') : undefined}><input type="password" value={password} onChange={e => setPassword(e.target.value)} autoComplete={setup ? 'new-password' : 'current-password'} required minLength={setup ? 12 : 1} maxLength={1024} /></Field>
          {setup && <Field label={t('bootstrap')}><input type="password" value={secret} onChange={e => setSecret(e.target.value)} autoComplete="off" required /></Field>}
          <Feedback error={mutation.error} />
          <Button type="submit" busy={mutation.isPending}>{t(setup ? 'setup' : 'login')}<ArrowRight size={17} /></Button>
        </form>
        <small className="auth-foot"><ShieldCheck size={14} /> {t('security')}</small>
      </div>
    </main>
  </div>
}
