import { McpSettings } from '../components/mcp'
import { PageHeader } from '../components/ui'
import { useLocale } from '../lib/i18n'

export default function McpPage() {
  const { language } = useLocale()
  return <><PageHeader title="MCP" description={language === 'de' ? 'Externe Clients und ihre Zugriffsrechte verwalten.' : 'Manage external clients and their access.'} /><McpSettings /></>
}
