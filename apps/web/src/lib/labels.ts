// One place for every backend enum shown in the UI, so values never appear as raw English codes.
type Pair = [de: string, en: string]
const LABELS: Record<string, Record<string, Pair>> = {
  purpose: { checking: ['Girokonto', 'Current account'], savings: ['Sparen / Topf', 'Savings / pot'], investment: ['Depot / Anlage', 'Investment'], credit: ['Kreditkarte / Kredit', 'Credit'], cash: ['Bargeld', 'Cash'], other: ['Steuer / Sonstiges', 'Tax / other'], mirror: ['Spiegelkonto (z. B. PayPal)', 'Mirror (e.g. PayPal)'] },
  ownership: { owned: ['Eigenes Konto', 'Owned'], external: ['Fremdes Konto', 'External'], unknown: ['Nicht zugeordnet', 'Unassigned'] },
  period: { monthly: ['monatlich', 'monthly'], quarterly: ['vierteljährlich', 'quarterly'], half_yearly: ['halbjährlich', 'half-yearly'], yearly: ['jährlich', 'yearly'], once: ['einmalig', 'once'], weekly: ['wöchentlich', 'weekly'] },
  importStatus: { completed: ['abgeschlossen', 'completed'], failed: ['fehlgeschlagen', 'failed'], error: ['Fehler', 'error'], queued: ['wartet', 'queued'], processing: ['läuft', 'processing'], pending: ['wartet', 'pending'], interrupted: ['unterbrochen', 'interrupted'] },
  runState: { reserved: ['reserviert', 'reserved'], settled: ['abgerechnet', 'settled'], released: ['freigegeben', 'released'], uncertain: ['unklar', 'uncertain'], queued: ['wartet', 'queued'], sent: ['gesendet', 'sent'], suppressed: ['unterdrückt', 'suppressed'], sending: ['wird gesendet', 'sending'], failed: ['fehlgeschlagen', 'failed'] },
  confidence: { low: ['niedrig', 'low'], medium: ['mittel', 'medium'], high: ['hoch', 'high'] },
  findingStatus: { open: ['offen', 'open'], dismissed: ['verworfen', 'dismissed'], resolved: ['erledigt', 'resolved'] },
  wishStatus: { open: ['offen', 'open'], bought: ['gekauft', 'bought'], dropped: ['verworfen', 'dropped'] },
  source: { employment: ['Gehalt', 'Employment'], business: ['Nebengewerbe', 'Business'], other: ['Sonstiges', 'Other'] },
  view: { all_transactions: ['Alle Buchungen', 'All transactions'], included_spending: ['Einbezogene Ausgaben', 'Included spending'], owned_liquid: ['Eigene liquide Konten', 'Owned liquid accounts'] },
  event: { weekly: ['Wöchentlich', 'Weekly'], monthly: ['Monatlich', 'Monthly'], report_ready: ['Bericht fertig', 'Report ready'], anomaly: ['Auffälligkeit', 'Anomaly'], import_changed: ['Import geändert', 'Import changed'], plan_exceeded: ['Soll fast erreicht oder überschritten', 'Plan nearly reached or exceeded'], reminder: ['Fristen & fällige Posten', 'Deadlines & due items'], test: ['Test', 'Test'] },
  kind: { subscription: ['Abo', 'Subscription'], insurance: ['Versicherung', 'Insurance'], utility: ['Versorger', 'Utility'], housing: ['Wohnen', 'Housing'], loan: ['Kredit', 'Loan'], savings: ['Sparplan', 'Savings plan'], other: ['Sonstiges', 'Other'], real: ['Kontogebunden', 'Account-backed'], virtual: ['Virtuell', 'Virtual'] },
}

export function label(group: keyof typeof LABELS | string, value: string | null | undefined, language: string): string {
  if (value == null || value === '') return '—'
  const pair = LABELS[group]?.[value]
  return pair ? pair[language === 'de' ? 0 : 1] : value
}
