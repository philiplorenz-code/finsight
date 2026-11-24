import { describe, expect, it } from 'vitest'
import { cancelLetter, deadlineIcs } from '../lib/cancel-letter'

const sender = { name: 'Synthetic Person', address: 'Musterweg 1\n12345 Musterstadt', city: 'Musterstadt' }

describe('cancel letter', () => {
  it('names the term end, customer number and asks for confirmation', () => {
    const text = cancelLetter({ sender, provider: 'Synthetic Gym GmbH', providerAddress: 'Hauptstr. 2\n54321 Beispielstadt', contract: 'Synthetic Gym',
      customerNumber: 'SYN-4711', termEnd: '2027-03-31', today: new Date('2026-11-24T10:00:00') })
    expect(text.startsWith('Synthetic Person\nMusterweg 1')).toBe(true)
    expect(text).toContain('Musterstadt, 24.11.2026')
    expect(text).toContain('Kündigung Synthetic Gym, Kundennummer SYN-4711')
    expect(text).toContain('fristgerecht zum 31.03.2027, hilfsweise zum nächstmöglichen Zeitpunkt')
    expect(text).toContain('schriftlich')
  })
  it('falls back to the next possible date without a known term end', () => {
    const text = cancelLetter({ sender, provider: 'X', providerAddress: '', contract: 'Abo', customerNumber: '', today: new Date('2026-11-24T10:00:00') })
    expect(text).toContain('fristgerecht zum nächstmöglichen Zeitpunkt.')
    expect(text).not.toContain('Kundennummer')
    expect(text).not.toMatch(/\n{4,}/)
  })
})

describe('deadline ics', () => {
  it('is an all-day event with two alarms', () => {
    const ics = deadlineIcs('Synthetic, Gym', '2026-12-31', 'abc')
    expect(ics).toContain('DTSTART;VALUE=DATE:20261231')
    expect(ics).toContain('DTEND;VALUE=DATE:20270101')
    expect(ics).toContain('SUMMARY:Letzter Tag zum Kündigen: Synthetic\\, Gym')
    expect(ics.match(/BEGIN:VALARM/g)).toHaveLength(2)
  })
})
