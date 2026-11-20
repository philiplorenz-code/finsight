// German texts for the backend's English warning strings. Unknown strings fall back to the original.
const DE: Record<string, string> = {
  'Account identity uses source name fallback; renamed exports may require reconciliation': 'Konten werden über den Namen aus der Datei erkannt; umbenannte Konten können einen Abgleich erfordern.',
  'Duplicate booking identities preserved with occurrence suffix; reconciliation uncertain': 'Doppelte Buchungs-IDs wurden mit Nummer erhalten; der Abgleich ist unsicher.',
  'Historical allocation snapshots unavailable; current allocations not subtracted': 'Für früher gibt es keine Zuteilungsstände; aktuelle Zuteilungen werden nicht abgezogen.',
  'Historical views use current account inclusion, purpose and planned obligations; these are not versioned': 'Historische Ansichten nutzen die aktuelle Kontozuordnung und Verpflichtungen; diese sind nicht versioniert.',
  'Missing booking IDs: conservative content identity used; identical rows are ambiguous': 'Buchungs-IDs fehlen: Buchungen werden über ihren Inhalt erkannt; identische Zeilen sind nicht eindeutig.',
  'One-sided transfers excluded; ownership uncertain': 'Einseitige Umbuchungen (Gegenkonto nicht importiert) werden nicht mitgezählt.',
  'Records missing from a later full snapshot retained': 'Buchungen, die in einem späteren Vollexport fehlen, bleiben erhalten.',
  'Split metadata present without proven child-parent mapping; reconciliation requires review': 'Split-Daten ohne belegte Zuordnung zur Hauptbuchung; der Abgleich muss geprüft werden.',
  'Split reconciliation uncertain': 'Der Split-Abgleich ist unsicher.',
  'Allocation backing is ineligible: account must be included, owned, liquid and same-currency': 'Die Deckung ist unzulässig: Das Konto muss eingeschlossen, dein eigenes, liquide und in derselben Währung sein.',
  'Allocation has no observed balance backing': 'Für die Zuteilung gibt es keinen beobachteten Kontostand als Deckung.',
  'Allocation is underfunded by latest observed funds; nominal intent is not funded money': 'Die Zuteilung ist durch den letzten Kontostand nicht gedeckt; ein Vorhaben ist noch kein vorhandenes Geld.',
  'Balance is latest observation on or before end; it is not reconstructed at end.': 'Der Kontostand ist die letzte Beobachtung bis zum Enddatum und wird nicht rekonstruiert.',
  'Buckets/obligations are current plans, not historical snapshots. Backing uses observed balances at end.': 'Töpfe und Verpflichtungen sind aktuelle Planwerte, keine historischen Stände. Die Deckung nutzt Kontostände zum Ende.',
  'Calculation cap reached; funding amounts unavailable.': 'Rechengrenze erreicht; Deckungsbeträge nicht verfügbar.',
  'Import time does not establish source transaction or balance coverage.': 'Der Importzeitpunkt belegt nicht, wie weit Buchungen und Kontostände abgedeckt sind.',
  'Missing records flagged only for accounts present in this explicitly declared full snapshot': 'Fehlende Buchungen werden nur für Konten markiert, die im ausdrücklich als Vollexport gekennzeichneten Import enthalten sind.',
  'Multiple same-day balances: final source-row observation used; intraday ordering unverified': 'Mehrere Kontostände am selben Tag: Es gilt der letzte aus der Datei; die Reihenfolge innerhalb des Tages ist ungeprüft.',
  'No account is marked as owned; classify accounts before relying on this assessment': 'Kein Konto ist als eigenes markiert; ordne die Konten zu, bevor du dich auf die Einschätzung verlässt.',
  'No observed balances; cash on hand is assumed to be zero': 'Keine Kontostände vorhanden; das Bargeld wird mit 0 angesetzt.',
  'No tax cost is modelled; if you owe tax on irregular income, set a monthly tax reserve': 'Steuern sind nicht berücksichtigt; bei unregelmäßigem Einkommen eine monatliche Steuerrücklage festlegen.',
  'One-sided or ambiguous transfers excluded from consumption; counterpart ownership unverified': 'Einseitige oder mehrdeutige Umbuchungen zählen nicht zum Verbrauch; das Gegenkonto ist nicht als eigenes bestätigt.',
  'Periods may have unequal durations; totals are not normalized.': 'Die Zeiträume können unterschiedlich lang sein; die Summen sind nicht normiert.',
  'Planned obligations and bucket targets are current values, not versioned': 'Geplante Verpflichtungen und Topfziele sind aktuelle Werte und nicht versioniert.',
  'Recurrence is a heuristic, not a contract or forecast; maximum 2000 source rows examined.': 'Wiederkehrende Zahlungen sind eine Schätzung, kein Vertrag und keine Prognose; höchstens 2000 Zeilen geprüft.',
  'Result byte cap reached; use a smaller page size.': 'Größenlimit erreicht; wähle eine kleinere Seitengröße.',
  'Some accounts have no balance observation on or before this day and are not counted': 'Zu manchen Konten gibt es bis zu diesem Tag keinen Kontostand; sie zählen nicht mit.',
  'Some observed balances are stale (older than seven days).': 'Einige Kontostände sind älter als 7 Tage.',
  'Some transfers are uncertain; the consumption figure may be slightly off': 'Einige Umbuchungen sind unsicher; der Verbrauch kann leicht abweichen.',
  'Source row cap reached; narrow date/account filters. Recurring total is partial.': 'Zeilenlimit erreicht; Zeitraum oder Konten eingrenzen. Die Summe der wiederkehrenden Zahlungen ist unvollständig.',
  'Split reconciliation uncertain; unmatched children excluded when parent exists': 'Split-Abgleich unsicher; nicht zuordenbare Teilbuchungen werden ausgeschlossen, wenn die Hauptbuchung existiert.',
  'Tax accounts exist but no tax outflow was found; set a monthly tax reserve': 'Es gibt Steuerkonten, aber keine Steuerzahlung; lege eine monatliche Steuerrücklage fest.',
  'Transaction data is stale; import a fresh export': 'Die Buchungsdaten sind veraltet; importiere einen frischen Export.',
  'Undated obligations included; recurring dates not projected; overdue items outside period omitted.': 'Verpflichtungen ohne Datum sind enthalten; Wiederholungstermine werden nicht fortgeschrieben; überfällige Posten außerhalb des Zeitraums fehlen.',
}
const PATTERNS: [RegExp, (m: RegExpMatchArray) => string][] = [
  [/^Data gaps in the analysis window for (\d+) account\(s\); see the imports page/, m => `Im Analysezeitraum gibt es Datenlücken bei ${m[1]} Konto/Konten; siehe Importseite.`],
  [/^Only (\d+) complete month\(s\) of data are available/, m => `Es liegen nur ${m[1]} vollständige Monate an Daten vor.`],
]

export function localizeWarning(text: string, language: string): string {
  if (language !== 'de') return text
  if (DE[text]) return DE[text]
  for (const [re, fn] of PATTERNS) { const m = text.match(re); if (m) return fn(m) }
  return text
}
