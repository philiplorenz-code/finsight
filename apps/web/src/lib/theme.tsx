import { createContext, useContext, useEffect, useState, type ReactNode } from 'react'
const Theme = createContext({ dark: false, toggle: () => {} })
export function ThemeProvider({ children }: { children: ReactNode }) {
  const [dark, setDark] = useState(() => localStorage.getItem('finsight-theme') === 'dark' || (!localStorage.getItem('finsight-theme') && matchMedia('(prefers-color-scheme: dark)').matches))
  useEffect(() => { document.documentElement.classList.toggle('dark', dark); localStorage.setItem('finsight-theme', dark ? 'dark' : 'light') }, [dark])
  return <Theme.Provider value={{ dark, toggle: () => setDark(d => !d) }}>{children}</Theme.Provider>
}
export const useTheme = () => useContext(Theme)
