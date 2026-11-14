import { useRef, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { CloudUpload, FileSpreadsheet, ShieldCheck, X } from 'lucide-react'
import { api, items } from '../lib/api'
import type { Import } from '../lib/types'
import { formatDate, useLocale } from '../lib/i18n'
import { Badge, Button, DataTable, Feedback, Notice, PageHeader, Panel, QueryState } from '../components/ui'

type Preview = { row_count?: number; columns?: string[]; warnings?: string[]; preview?: Record<string, unknown>[]; rows?: Record<string, unknown>[]; preview_id?: string }
export default function ImportsPage() {
  const { t, language } = useLocale(); const client = useQueryClient()
  const [file, setFile] = useState<File | null>(null)
  const [fileError, setFileError] = useState(false)
  const [dragging, setDragging] = useState(false)
  const input = useRef<HTMLInputElement>(null)
  const query = useQuery({ queryKey: ['imports'], queryFn: async () => items(await api<Import[] | { items: Import[] }>('/imports')).map(i => ({ ...i, imported: i.summary?.added ?? i.imported, updated: i.summary?.changed ?? i.updated, unchanged: i.summary?.unchanged ?? i.unchanged })), refetchInterval: q => items(q.state.data).some(i => ['queued', 'processing', 'pending', 'running'].includes(i.status)) ? 2500 : false })
  const preview = useMutation({ mutationFn: async () => { const body = new FormData(); body.append('file', file!); return api<Preview>('/imports/preview', { method: 'POST', body }) } })
  const upload = useMutation({ mutationFn: async () => { const body = new FormData(); body.append('file', file!); return api('/imports', { method: 'POST', body }) }, onSuccess: () => { setFile(null); preview.reset(); if (input.current) input.current.value = ''; client.invalidateQueries({ queryKey: ['imports'] }); client.invalidateQueries({ queryKey: ['overview'] }); client.invalidateQueries({ queryKey: ['accounts'] }); client.invalidateQueries({ queryKey: ['transactions'] }) } })
  const choose = (chosen?: File) => { if (!chosen || preview.isPending || upload.isPending) return; setFileError(!chosen.name.toLowerCase().endsWith('.xlsx') || chosen.size > 25 * 1024 * 1024 || chosen.size === 0); setFile(chosen.name.toLowerCase().endsWith('.xlsx') && chosen.size <= 25 * 1024 * 1024 && chosen.size > 0 ? chosen : null); preview.reset(); upload.reset(); if (input.current) input.current.value = '' }
  const previewRows = preview.data?.preview || preview.data?.rows || []
  const columns = preview.data?.columns || Object.keys(previewRows[0] || {})
  return <>
    <PageHeader title={t('imports')} description={t('importsIntro')} />
    <Panel>
      <div className={`dropzone ${dragging ? 'dragging' : ''}`} onDragOver={e => { e.preventDefault(); setDragging(true) }} onDragLeave={() => setDragging(false)} onDrop={e => { e.preventDefault(); setDragging(false); choose(e.dataTransfer.files[0]) }}>
        <span className="upload-icon"><CloudUpload size={30} /></span><h2>{t('drop')}</h2><p>{t('dropText')}</p>
        <input ref={input} type="file" accept=".xlsx,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" className="sr-only" aria-label={t('choose')} onChange={e => choose(e.target.files?.[0])} disabled={preview.isPending || upload.isPending} />
        <Button variant="outline" onClick={() => input.current?.click()} disabled={preview.isPending || upload.isPending}>{t('choose')}</Button>
      </div>
      <p className="upload-privacy"><ShieldCheck size={15} />{t('importPrivacy')}</p>
      {fileError && <div role="alert" className="feedback error">{t('fileError')}</div>}
      {file && <div className="selected-file"><FileSpreadsheet size={25} /><div><strong>{file.name}</strong><small>{(file.size / 1024).toFixed(1)} KB</small></div><Button variant="ghost" aria-label={t('cancel')} disabled={preview.isPending || upload.isPending} onClick={() => { setFile(null); preview.reset() }}><X size={17} /></Button><Button onClick={() => preview.mutate()} busy={preview.isPending} disabled={upload.isPending}>{t('preview')}</Button></div>}
      <Feedback error={preview.error || upload.error} success={upload.isSuccess} />
      {preview.data && <div className="preview"><div className="panel-heading"><h2>{t('preview')} <Badge>{preview.data.row_count ?? '—'} {t('rows')}</Badge></h2><Button onClick={() => upload.mutate()} busy={upload.isPending}>{t('upload')}</Button></div>{preview.data.warnings?.map((w, i) => <Notice key={i} warning>{w}</Notice>)}
        <div className="badge-row">{columns.map(c => <Badge key={c}>{c}</Badge>)}</div>
        {!!previewRows.length && <DataTable headers={columns}>{previewRows.slice(0, 10).map((row, i) => <tr key={i}>{columns.map(c => <td key={c}>{typeof row[c] === 'object' ? JSON.stringify(row[c]) : String(row[c] ?? '')}</td>)}</tr>)}</DataTable>}
        <Notice>{t('importWarning')}</Notice>
      </div>}
    </Panel>
    <Panel title={t('history')} description={t('reconciliation')}>
      <QueryState pending={query.isPending} error={query.error} retry={query.refetch} empty={!items(query.data).length}>
        <DataTable headers={[t('name'), t('date'), t('status'), t('rows'), t('reconciliation')]}>{items(query.data).map(i => <tr key={i.id}><td><div className="file-name"><FileSpreadsheet size={18} />{i.filename || i.id}</div></td><td className="nowrap muted">{formatDate(i.created_at, language)}</td><td><Badge tone={['failed', 'error'].includes(i.status) ? 'warning' : ''}>{i.status}</Badge></td><td>{i.row_count ?? '—'}</td><td className="small muted">{language === 'de' ? 'Neu / Geändert / Unverändert' : 'New / Updated / Unchanged'}: {i.summary?.inserted ?? i.imported ?? '—'} / {i.summary?.updated ?? i.updated ?? '—'} / {i.summary?.unchanged ?? i.unchanged ?? '—'}{['failed', 'error'].includes(i.status) && <p>{language === 'de' ? 'Bitte Datei erneut auswählen und importieren.' : 'Please select the file again to retry the import.'}</p>}</td></tr>)}</DataTable>
      </QueryState>
    </Panel>
  </>
}
