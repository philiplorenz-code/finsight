import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Bell, KeyRound, Monitor, ShieldCheck, Sparkles } from 'lucide-react'
import { api, items, send } from '../lib/api'
import { formatDate, useLocale } from '../lib/i18n'
import { PhoneImport } from '../components/phone-import'
import { label } from '../lib/labels'
import { useTheme } from '../lib/theme'
import { Badge, Button, DataTable, Feedback, Field, Notice, PageHeader, Panel, QueryState } from '../components/ui'
import { McpSettingsLink } from '../components/mcp'

export type AIPolicy = {
  budget_currency: string | null
  enabled: boolean; external_consent: boolean; proactive_consent: boolean; model: string
  prices: Record<string, { input: string; output: string; currency: string; verified: boolean }>
  total_limit: string; monthly_limit: string; channel_limits: Record<string, string>; run_limit: string
  max_concurrent: number; max_input_tokens: number; max_output_tokens: number; max_tools: number; max_steps: number; timeout_seconds: number
}
type Notifications = { enabled: boolean; server: string; topic: string; timezone: string; quiet_start: number; quiet_end: number; stale_after_hours: number; events: string[]; reminder_hour: number; weekly_day: number }
export type SettingsData = { ai?: AIPolicy; notifications?: Notifications; ai_enabled?: boolean; external_ai_consent?: boolean }
const defaultAI: AIPolicy = { budget_currency: 'EUR', enabled: false, external_consent: false, proactive_consent: false, model: '', prices: {}, total_limit: '0', monthly_limit: '0', channel_limits: { chat: '0', weekly: '0', monthly: '0', changed_import: '0' }, run_limit: '0', max_concurrent: 1, max_input_tokens: 4096, max_output_tokens: 512, max_tools: 3, max_steps: 6, timeout_seconds: 30 }
const defaultNotifications: Notifications = { enabled: false, server: '', topic: '', timezone: 'Europe/Berlin', quiet_start: 1320, quiet_end: 480, stale_after_hours: 168, events: [], reminder_hour: 9, weekly_day: 0 }
const toTime = (minutes: number) => `${String(Math.floor(minutes / 60)).padStart(2, '0')}:${String(minutes % 60).padStart(2, '0')}`
const toMinutes = (time: string) => { const [h, m] = time.split(':').map(Number); return h * 60 + m }

const EVENT_DE: Record<string, string> = { weekly: 'Wöchentlich', monthly: 'Monatlich', report_ready: 'Bericht fertig', anomaly: 'Auffälligkeit', import_changed: 'Import geändert', plan_exceeded: 'Soll überschritten' }
export default function SettingsPage() {
  const { t, language, setLanguage } = useLocale(); const { dark, toggle } = useTheme()
  const query = useQuery({ queryKey: ['settings'], queryFn: () => api<SettingsData>('/settings') })
  return <>
    <PageHeader title={t('settings')} description={t('settingsIntro')} />
    <div className="mcp-settings-link"><McpSettingsLink /></div>
    <Panel title={t('appearance')} action={<Monitor size={19} />}>
      <div className="settings-appearance">
        <Field label={t('language')}><select value={language} onChange={e => setLanguage(e.target.value as 'de' | 'en')}><option value="de">Deutsch</option><option value="en">English</option></select></Field>
        <Field label={t('theme')}><div className="segmented"><button aria-pressed={!dark} onClick={() => { if (dark) toggle() }}>{t('light')}</button><button aria-pressed={dark} onClick={() => { if (!dark) toggle() }}>{t('dark')}</button></div></Field>
      </div>
    </Panel>
    <AccountSecurity />
    <PhoneImport />
    <QueryState pending={query.isPending} error={query.error} retry={query.refetch}>{query.data && <IntegrationSettings initial={query.data} />}</QueryState>
    <NotificationHistory />
  </>
}
function IntegrationSettings({ initial }: { initial: SettingsData }) {
  const { t, language } = useLocale(); const client = useQueryClient()
  const [ai, setAI] = useState<AIPolicy>({ ...defaultAI, ...initial.ai })
  const [notifications, setNotifications] = useState<Notifications>({ ...defaultNotifications, ...initial.notifications })
  const legacyPolicy = !!initial.ai && (initial.ai.budget_currency !== 'EUR' || Object.values(initial.ai.prices || {}).some(p => p.currency !== 'EUR'))
  const price = ai.prices[ai.model] || { input: '0', output: '0', currency: 'EUR' as const, verified: false }
  const updatePrice = (key: 'input' | 'output' | 'verified', value: string | boolean) => setAI({ ...ai, prices: { ...ai.prices, [ai.model]: { ...price, [key]: value } } })
  const mutation = useMutation({ mutationFn: () => send('/settings', { ...(!legacyPolicy ? { ai } : {}), notifications }, 'PATCH'), onSuccess: () => client.invalidateQueries({ queryKey: ['settings'] }) })
  const environment = useMutation({ mutationFn: (revoke: boolean) => send('/ai/consent', revoke ? { enabled: false, external_consent: false, proactive_consent: false } : { enabled: ai.enabled, external_consent: ai.external_consent, proactive_consent: ai.proactive_consent }), onSuccess: async () => {
    const saved = await client.fetchQuery({ queryKey: ['settings'], queryFn: () => api<SettingsData>('/settings'), staleTime: 0 })
    if (saved.ai) setAI({ ...defaultAI, ...saved.ai })
    await client.invalidateQueries({ queryKey: ['ai-usage'] })
  } })
  const notification = useMutation({ mutationFn: () => send<{ state?: string }>('/notifications/test'), onSettled: () => client.invalidateQueries({ queryKey: ['notifications'] }) })
  const aiValid = legacyPolicy || !ai.enabled || (ai.external_consent && ai.model && price.currency === 'EUR' && price.verified && Number(ai.monthly_limit) > 0 && Number(ai.run_limit) > 0 && Number(ai.total_limit) > 0 && Number(ai.channel_limits.chat) > 0)
  return <form className="form-stack settings-form" onSubmit={e => { e.preventDefault(); mutation.mutate() }}>
    <Panel title={t('aiEnabled')} action={<Sparkles size={19} />}>
      {legacyPolicy ? <Notice warning>{language === 'de' ? 'Historische KI-Richtlinie: Währung' : 'Legacy AI policy: currency'} {initial.ai?.budget_currency || (language === 'de' ? 'unbekannt' : 'unknown')}. {language === 'de' ? 'Keine Umrechnung in EUR. Eine geprüfte serverseitige Abstimmung ist vor Änderungen erforderlich. Monatliches Altlimit:' : 'No conversion to EUR. Audited server-side reconciliation is required before changes. Historical monthly limit:'} {initial.ai?.monthly_limit}. {language === 'de' ? 'Preiswährungen:' : 'Price currencies:'} {[...new Set(Object.values(initial.ai?.prices || {}).map(p => p.currency || '?'))].join(', ') || '?'}</Notice> : <div className="form-stack">
        <Notice>{t('aiNote')}</Notice>
        <label className="checkbox"><input type="checkbox" checked={ai.enabled} onChange={e => setAI({ ...ai, enabled: e.target.checked })} />{t('aiEnabled')}</label>
        <label className="checkbox"><input type="checkbox" checked={ai.external_consent} onChange={e => setAI({ ...ai, external_consent: e.target.checked, ...(!e.target.checked ? { enabled: false, proactive_consent: false } : {}) })} />{t('consent')}</label>
        <label className="checkbox"><input type="checkbox" checked={ai.proactive_consent} disabled={!ai.external_consent} onChange={e => setAI({ ...ai, proactive_consent: e.target.checked })} />{t('proactive')}</label>
        <Notice>{language === 'de' ? 'Ausgehende KI-Aufrufe erfordern zusätzlich AI_ENABLED=true, AI_EXTERNAL_CONSENT=true und gültige Provider-/Modellkonfiguration auf dem Server. Effektive Limits sind jeweils das Minimum aus Richtlinie und Server-Caps. Eine gespeicherte Zustimmung bestätigt keine aktive Provider-Verbindung.' : 'Outbound AI also requires AI_ENABLED=true, AI_EXTERNAL_CONSENT=true and valid provider/model configuration on the server. Effective limits are the minimum of policy and server caps. Saved consent does not confirm an active provider connection.'}</Notice>
        <div><Button type="button" variant="outline" busy={environment.isPending} disabled={mutation.isPending || !ai.enabled || !ai.external_consent} onClick={() => environment.mutate(false)}>{language === 'de' ? 'Serverkonfiguration mit Zustimmung übernehmen' : 'Apply server configuration with consent'}</Button></div>
        <div className="form-grid">
          <Field label={t('budgetEur')}><input type="number" required min="0" step="0.00000001" value={ai.monthly_limit} onChange={e => setAI({ ...ai, monthly_limit: e.target.value })} /></Field>
          <Field label={language === 'de' ? 'Gesamtlimit (EUR)' : 'Lifetime limit (EUR)'}><input type="number" required min="0" step="0.00000001" value={ai.total_limit} onChange={e => setAI({ ...ai, total_limit: e.target.value })} /></Field>
          <Field label={language === 'de' ? 'Limit je Anfrage (EUR)' : 'Per-request limit (EUR)'}><input type="number" required min="0" step="0.00000001" value={ai.run_limit} onChange={e => setAI({ ...ai, run_limit: e.target.value })} /></Field>
          <Field label={language === 'de' ? 'Chat-Limit / Monat (EUR)' : 'Chat limit / month (EUR)'}><input type="number" required min="0" step="0.00000001" value={ai.channel_limits.chat || '0'} onChange={e => setAI({ ...ai, channel_limits: { ...ai.channel_limits, chat: e.target.value } })} /></Field>
        </div>
        <details>
          <summary>{language === 'de' ? 'Modell, verifizierte Preise & Sicherheitsgrenzen' : 'Model, verified prices & safety limits'}</summary>
          <div className="form-stack">
            <Notice warning>{language === 'de' ? 'Provider-Zugangsdaten nur auf dem Server konfigurieren. Preise müssen vom Anbieter bestätigt sein; fehlende Abrechnungsdaten sperren die Anfrage.' : 'Configure provider credentials only on the server. Prices must be verified with the provider; missing billing data blocks requests.'}</Notice>
            <Field label="Model ID"><input maxLength={160} value={ai.model} onChange={e => setAI({ ...ai, model: e.target.value })} /></Field>
            <div className="form-grid">
              <Field label="Input · EUR / 1M tokens"><input type="number" min="0" step="0.00000001" disabled={!ai.model} value={price.input} onChange={e => updatePrice('input', e.target.value)} /></Field>
              <Field label="Output · EUR / 1M tokens"><input type="number" min="0" step="0.00000001" disabled={!ai.model} value={price.output} onChange={e => updatePrice('output', e.target.value)} /></Field>
            </div>
            <label className="checkbox"><input type="checkbox" disabled={!ai.model} checked={price.verified} onChange={e => updatePrice('verified', e.target.checked)} />{language === 'de' ? 'Ich habe diese EUR-Preise beim Provider verifiziert.' : 'I verified these EUR prices with the provider.'}</label>
            <div className="form-grid">
              {([['max_input_tokens', 128, 32000], ['max_output_tokens', 1, 4096], ['max_tools', 1, 3], ['max_steps', 3, 8], ['max_concurrent', 1, 8], ['timeout_seconds', 1, 120]] as const).map(([key, min, max]) => <Field key={key} label={key.replaceAll('_', ' ')}><input type="number" min={min} max={max} required value={ai[key]} onChange={e => setAI({ ...ai, [key]: Number(e.target.value) })} /></Field>)}
              {(['weekly', 'monthly', 'changed_import'] as const).map(key => <Field key={key} label={`${key} · EUR / month`}><input type="number" min="0" step="0.00000001" value={ai.channel_limits[key] || '0'} onChange={e => setAI({ ...ai, channel_limits: { ...ai.channel_limits, [key]: e.target.value } })} /></Field>)}
            </div>
          </div>
        </details>
      </div>}
      <div className="form-actions"><Button type="button" variant="outline" disabled={mutation.isPending} busy={environment.isPending} onClick={() => environment.mutate(true)}>{language === 'de' ? 'KI-Zustimmung widerrufen' : 'Revoke AI consent'}</Button></div>
      <Feedback error={environment.error} success={environment.isSuccess} />
    </Panel>
    <Panel title={t('notifications')} action={<Bell size={19} />}>
      <div className="form-stack">
        <Notice>{t('notificationNote')}</Notice>
        <label className="checkbox"><input type="checkbox" checked={notifications.enabled} onChange={e => setNotifications({ ...notifications, enabled: e.target.checked })} />{t('enabled')}</label>
        <div className="form-grid">
          <Field label={t('ntfyServer')}><input type="url" pattern="https://.*" required={notifications.enabled} placeholder="https://ntfy.example.org" value={notifications.server} onChange={e => setNotifications({ ...notifications, server: e.target.value })} /></Field>
          <Field label={t('ntfyTopic')}><input autoComplete="off" required={notifications.enabled} maxLength={100} value={notifications.topic} onChange={e => setNotifications({ ...notifications, topic: e.target.value })} /></Field>
          <Field label={t('timezone')}><input required value={notifications.timezone} onChange={e => setNotifications({ ...notifications, timezone: e.target.value })} /></Field>
          <Field label={t('quietStart')}><input type="time" required value={toTime(notifications.quiet_start)} onChange={e => setNotifications({ ...notifications, quiet_start: toMinutes(e.target.value) })} /></Field>
          <Field label={t('quietEnd')}><input type="time" required value={toTime(notifications.quiet_end)} onChange={e => setNotifications({ ...notifications, quiet_end: toMinutes(e.target.value) })} /></Field>
          <Field label={language === 'de' ? 'Import maximal alt (Stunden)' : 'Maximum import age (hours)'}><input type="number" min={1} max={8760} required value={notifications.stale_after_hours} onChange={e => setNotifications({ ...notifications, stale_after_hours: Number(e.target.value) })} /></Field>
        </div>
        <div className="badge-row">{['weekly', 'monthly', 'report_ready', 'anomaly', 'import_changed', 'plan_exceeded', 'reminder'].map(event => <label className="checkbox" key={event}><input type="checkbox" checked={notifications.events.includes(event)} onChange={e => setNotifications({ ...notifications, events: e.target.checked ? [...notifications.events, event] : notifications.events.filter(v => v !== event) })} />{label('event', event, language)}</label>)}</div>
        <p className="muted small">{language === 'de' ? 'Zugriffstoken ausschließlich als Server-Secret konfigurieren, nicht im Browser speichern. Vor einem Test Änderungen speichern.' : 'Configure access tokens only as server secrets, not in the browser. Save changes before testing.'}</p>
        <div><Button type="button" variant="outline" onClick={() => notification.mutate()} busy={notification.isPending} disabled={mutation.isPending}>{t('testNotification')}</Button></div>
        <Feedback error={notification.error} />
        {notification.isSuccess && <div role="status" className="notice">{language === 'de' ? 'Test verarbeitet. Zustellung ist noch nicht bestätigt. Status:' : 'Test processed. Delivery is not yet confirmed. Status:'} {notification.data?.state || '—'}</div>}
      </div>
    </Panel>
    <Feedback error={mutation.error} success={mutation.isSuccess} />
    {!aiValid && <Notice warning>{language === 'de' ? 'Zum Aktivieren: Zustimmung, verifiziertes Modell und positive Gesamt-, Monats-, Chat- und Anfragelimits festlegen.' : 'To enable: set consent, a verified model and positive lifetime, monthly, chat and request limits.'}</Notice>}
    <div className="settings-save"><span className="muted small"><ShieldCheck size={14} />{t('privateText')}</span><Button busy={mutation.isPending} disabled={!aiValid}>{t('save')}</Button></div>
  </form>
}

function NotificationHistory() {
  const { t, language } = useLocale()
  type Notification = { id: string; event: string; state: string; reason?: string; attempts?: number; created_at?: string; sent_at?: string }
  const query = useQuery({ queryKey: ['notifications'], queryFn: () => api<{ items: Notification[] } | Notification[]>('/notifications'), retry: false })
  return <div className="notification-history"><Panel title={`${t('notifications')} · ${t('history')}`}>
    <QueryState pending={query.isPending} error={query.error} retry={query.refetch} empty={!items(query.data).length}>
      <DataTable headers={[t('date'), language === 'de' ? 'Ereignis' : 'Event', t('status'), language === 'de' ? 'Hinweis' : 'Note']}>{items(query.data).map(n => <tr key={n.id}><td>{formatDate(n.created_at, language)}</td><td>{label('event', n.event, language)}</td><td><Badge>{n.state}</Badge></td><td className="muted">{n.reason || '—'}</td></tr>)}</DataTable>
    </QueryState>
  </Panel></div>
}


function AccountSecurity() {
  const { language } = useLocale()
  const de = language === 'de'
  const me = useQuery({ queryKey: ['me'], queryFn: () => api<{ email: string }>('/auth/me') })
  const [pw, setPw] = useState({ current: '', next: '', repeat: '' })
  const [mail, setMail] = useState({ current: '', email: '' })
  const mismatch = pw.next !== pw.repeat
  const changePassword = useMutation({
    mutationFn: () => send<{ sessions_revoked: number }>('/auth/change-password', { current_password: pw.current, new_password: pw.next }),
    onSuccess: () => setPw({ current: '', next: '', repeat: '' }),
  })
  const changeEmail = useMutation({
    mutationFn: () => send<{ email: string }>('/auth/change-email', { current_password: mail.current, email: mail.email }),
    onSuccess: () => { setMail({ current: '', email: '' }); me.refetch() },
  })
  return <Panel title={de ? 'Anmeldedaten' : 'Sign-in'} action={<KeyRound size={19} />} description={de
    ? `Angemeldet als ${me.data?.email ?? '…'}. Für jede Änderung brauchst du dein aktuelles Passwort. Nach einer Passwortänderung werden alle anderen Geräte abgemeldet.`
    : `Signed in as ${me.data?.email ?? '…'}. Changes need your current password; after a password change all other devices are signed out.`}>
    <div className="settings-grid-2">
      <form className="form-stack" onSubmit={e => { e.preventDefault(); if (!mismatch) changePassword.mutate() }}>
        <h3>{de ? 'Passwort ändern' : 'Change password'}</h3>
        <Field label={de ? 'Aktuelles Passwort' : 'Current password'}><input required type="password" autoComplete="current-password" value={pw.current} onChange={e => setPw({ ...pw, current: e.target.value })} /></Field>
        <Field label={de ? 'Neues Passwort' : 'New password'} hint={de ? 'Mindestens 12 Zeichen.' : 'At least 12 characters.'}><input required type="password" autoComplete="new-password" minLength={12} maxLength={1024} value={pw.next} onChange={e => setPw({ ...pw, next: e.target.value })} /></Field>
        <Field label={de ? 'Neues Passwort wiederholen' : 'Repeat new password'}><input required type="password" autoComplete="new-password" value={pw.repeat} onChange={e => setPw({ ...pw, repeat: e.target.value })} /></Field>
        {pw.repeat && mismatch && <Notice warning>{de ? 'Die beiden neuen Passwörter stimmen nicht überein.' : 'The two new passwords do not match.'}</Notice>}
        <Feedback error={changePassword.error} success={changePassword.isSuccess} />
        {changePassword.isSuccess && <p className="muted">{de ? `Passwort geändert, ${changePassword.data?.sessions_revoked ?? 0} andere Sitzung(en) abgemeldet.` : `Password changed, ${changePassword.data?.sessions_revoked ?? 0} other session(s) signed out.`}</p>}
        <Button busy={changePassword.isPending} disabled={mismatch || pw.next.length < 12}>{de ? 'Passwort ändern' : 'Change password'}</Button>
      </form>
      <form className="form-stack" onSubmit={e => { e.preventDefault(); changeEmail.mutate() }}>
        <h3>{de ? 'E-Mail ändern' : 'Change e-mail'}</h3>
        <Field label={de ? 'Neue E-Mail-Adresse' : 'New e-mail address'}><input required type="email" autoComplete="email" maxLength={254} value={mail.email} onChange={e => setMail({ ...mail, email: e.target.value })} /></Field>
        <Field label={de ? 'Aktuelles Passwort' : 'Current password'}><input required type="password" autoComplete="current-password" value={mail.current} onChange={e => setMail({ ...mail, current: e.target.value })} /></Field>
        <Feedback error={changeEmail.error} success={changeEmail.isSuccess} />
        <Button busy={changeEmail.isPending}>{de ? 'E-Mail ändern' : 'Change e-mail'}</Button>
      </form>
    </div>
  </Panel>
}
