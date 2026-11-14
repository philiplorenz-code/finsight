import { Component, type ReactNode } from 'react'
export class ErrorBoundary extends Component<{ children: ReactNode }, { failed: boolean }> {
  state = { failed: false }
  static getDerivedStateFromError() { return { failed: true } }
  render() {
    if (!this.state.failed) return this.props.children
    const english = localStorage.getItem('finsight-language') === 'en'
    return <main className="state" role="alert"><h1>FinSight</h1><p>{english ? 'This view could not be displayed. Reload to try again.' : 'Diese Ansicht konnte nicht angezeigt werden. Bitte lade die Seite neu.'}</p><button className="button button-primary" onClick={() => window.location.reload()}>{english ? 'Reload' : 'Neu laden'}</button></main>
  }
}
