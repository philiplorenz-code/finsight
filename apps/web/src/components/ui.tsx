import { cloneElement, isValidElement, useEffect, useId, useRef, type ButtonHTMLAttributes, type ReactNode } from 'react'
import { AlertCircle, ArrowUpRight, Check, Inbox, LoaderCircle, X } from 'lucide-react'
import { Link } from 'react-router-dom'
import { ApiError } from '../lib/api'
import { useLocale, type TranslationKey } from '../lib/i18n'

export function Button({ variant = 'primary', className = '', children, busy, ...props }: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: 'primary' | 'outline' | 'ghost' | 'danger'; busy?: boolean }) {
  return <button className={`button button-${variant} ${className}`} {...props} disabled={props.disabled || busy}>{busy && <LoaderCircle size={16} className="animate-spin" />}{children}</button>
}
export function Badge({ children, tone = '' }: { children: ReactNode; tone?: string }) { return <span className={`badge ${tone}`}>{children}</span> }
export function Field({ label, children, hint }: { label: string; children: ReactNode; hint?: string }) {
  const id = useId()
  if (isValidElement(children) && children.type === 'div') return <div className="field"><span id={`${id}-label`}>{label}</span><div role="group" aria-labelledby={`${id}-label`}>{children}</div>{hint && <small>{hint}</small>}</div>
  return <div className="field"><label htmlFor={id}>{label}</label>{isValidElement<{ id?: string; 'aria-describedby'?: string }>(children) ? cloneElement(children, { id, ...(hint ? { 'aria-describedby': `${id}-hint` } : {}) }) : children}{hint && <small id={`${id}-hint`}>{hint}</small>}</div>
}
export function Money({ value, currency = 'EUR', className = '' }: { value?: string | null; currency?: string; className?: string }) {
  const { language } = useLocale()
  return <span className={`money ${className}`}>{format(value, currency, language)}</span>
}
import { formatMoney as format } from '../lib/i18n'
export function PageHeader({ title, description, action, eyebrow }: { title: string; description?: string; action?: ReactNode; eyebrow?: string }) {
  return <header className="page-header"><div>{eyebrow && <span className="eyebrow">{eyebrow}</span>}<h1>{title}</h1>{description && <p>{description}</p>}</div>{action}</header>
}
export function Panel({ title, description, action, children, className = '' }: { title?: string; description?: string; action?: ReactNode; children: ReactNode; className?: string }) {
  return <section className={`panel ${className}`}>{title && <div className="panel-heading"><div><h2>{title}</h2>{description && <p>{description}</p>}</div>{action}</div>}{children}</section>
}
export function Notice({ children, warning = false }: { children: ReactNode; warning?: boolean }) { return <div className={`notice ${warning ? 'warning' : ''}`}><AlertCircle size={17} aria-hidden="true" /><div>{children}</div></div> }
export function Feedback({ error, success }: { error?: unknown; success?: boolean }) {
  const { t } = useLocale()
  if (error) {
    const key = error instanceof ApiError ? error.message : 'unavailable'
    return <div role="alert" className="feedback error"><AlertCircle size={17} />{t((['rate_limit', 'unauthorized', 'forbidden', 'conflict', 'invalid', 'ai_blocked'].includes(key) ? key : 'unavailable') as TranslationKey)}</div>
  }
  return success ? <div role="status" className="feedback success"><Check size={17} />{t('saved')}</div> : null
}
export function QueryState({ pending, error, retry, empty = false, importLink = false, children }: { pending: boolean; error: unknown; retry: () => unknown; empty?: boolean; importLink?: boolean; children: ReactNode }) {
  const { t } = useLocale()
  if (pending) return <div role="status" className="state"><LoaderCircle className="animate-spin" size={26} /><p>{t('loading')}</p><div className="skeleton-lines"><i /><i /><i /></div></div>
  if (error) return <div className="state" role="alert"><AlertCircle size={30} /><h2>{t('error')}</h2><p>{t('unavailable')}</p><Button variant="outline" onClick={retry}>{t('retry')}</Button></div>
  if (empty) return <div className="state empty"><div className="empty-icon"><Inbox size={30} /></div><h2>{t(importLink ? 'empty' : 'noResults')}</h2>{importLink && <><p>{t('emptyText')}</p><Link className="button button-primary" to="/imports">{t('import')}<ArrowUpRight size={16} /></Link></>}</div>
  return <>{children}</>
}
export function Dialog({ title, onClose, children }: { title: string; onClose: () => void; children: ReactNode }) {
  const ref = useRef<HTMLDialogElement>(null)
  const titleId = useId()
  useEffect(() => { const previous = document.activeElement as HTMLElement; ref.current?.showModal(); return () => previous?.focus() }, [])
  return <dialog ref={ref} className="dialog" aria-labelledby={titleId} onCancel={onClose} onClick={e => { if (e.target === ref.current) onClose() }}><div className="dialog-content"><div className="dialog-heading"><h2 id={titleId}>{title}</h2><Close onClick={onClose} /></div>{children}</div></dialog>
}
function Close({ onClick }: { onClick: () => void }) { const { t } = useLocale(); return <Button variant="ghost" onClick={onClick} aria-label={t('close')}><X size={20} /></Button> }
export function DataTable({ headers, children }: { headers: string[]; children: ReactNode }) {
  return <div className="table-scroll" tabIndex={0}><table><thead><tr>{headers.map((h, i) => <th key={`${h}-${i}`} scope="col" aria-label={h || 'Aktionen / Actions'}>{h}</th>)}</tr></thead><tbody>{children}</tbody></table></div>
}
