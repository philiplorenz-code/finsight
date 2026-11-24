/** Cancellation letter and calendar reminder, built in the browser only (nothing is sent anywhere). */
export type Sender = { name: string; address: string; city: string }
export type LetterInput = { sender: Sender; provider: string; providerAddress: string; contract: string; customerNumber: string; termEnd?: string | null; today: Date }

const german = (iso: string) => { const [y, m, d] = iso.slice(0, 10).split('-'); return `${d}.${m}.${y}` }

export function cancelLetter(input: LetterInput): string {
  const { sender, provider, providerAddress, contract, customerNumber, termEnd, today } = input
  const date = new Intl.DateTimeFormat('de-DE', { day: '2-digit', month: '2-digit', year: 'numeric' }).format(today)
  const subject = [`Kündigung ${contract}`.trim(), customerNumber.trim() && `Kundennummer ${customerNumber.trim()}`].filter(Boolean).join(', ')
  const when = termEnd ? `fristgerecht zum ${german(termEnd)}, hilfsweise zum nächstmöglichen Zeitpunkt` : 'fristgerecht zum nächstmöglichen Zeitpunkt'
  const block = (...lines: string[]) => lines.map(l => l.trim()).filter(Boolean).join('\n')
  return [
    block(sender.name, sender.address),
    block(provider, providerAddress),
    `${sender.city.trim() ? `${sender.city.trim()}, ` : ''}${date}`,
    subject,
    'Sehr geehrte Damen und Herren,',
    `hiermit kündige ich den oben genannten Vertrag ${when}.`,
    'Bitte bestätigen Sie mir den Eingang dieser Kündigung und das genaue Vertragsende schriftlich. Ein erteiltes SEPA-Lastschriftmandat widerrufe ich zum Vertragsende. Der Nutzung meiner Daten zu Werbezwecken widerspreche ich.',
    `Mit freundlichen Grüßen\n\n\n${sender.name.trim()}`.trimEnd(),
  ].filter(Boolean).join('\n\n')
}

const icsDate = (iso: string) => iso.slice(0, 10).replace(/-/g, '')
const escape = (text: string) => text.replace(/[\\,;]/g, c => `\\${c}`).replace(/\n/g, '\\n')

/** All-day calendar entry on the cancel-by date with alarms 14 and 3 days before. */
export function deadlineIcs(name: string, cancelBy: string, uid: string): string {
  const next = new Date(`${cancelBy.slice(0, 10)}T00:00:00Z`); next.setUTCDate(next.getUTCDate() + 1)
  const alarm = (days: number) => ['BEGIN:VALARM', 'ACTION:DISPLAY', `DESCRIPTION:${escape(`Kündigen: ${name}`)}`, `TRIGGER:-P${days}D`, 'END:VALARM']
  return ['BEGIN:VCALENDAR', 'VERSION:2.0', 'PRODID:-//FinSight//Kuendigung//DE', 'BEGIN:VEVENT', `UID:${uid}@finsight.local`,
    `DTSTAMP:${new Date().toISOString().replace(/[-:]/g, '').slice(0, 15)}Z`, `DTSTART;VALUE=DATE:${icsDate(cancelBy)}`,
    `DTEND;VALUE=DATE:${next.toISOString().slice(0, 10).replace(/-/g, '')}`, `SUMMARY:${escape(`Letzter Tag zum Kündigen: ${name}`)}`,
    ...alarm(14), ...alarm(3), 'END:VEVENT', 'END:VCALENDAR', ''].join('\r\n')
}
