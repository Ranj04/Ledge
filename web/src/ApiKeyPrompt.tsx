import { useEffect, useState } from 'react'

const STORAGE_KEY = 'memoryledger-api-key'

export function ApiKeyPrompt() {
  const [open, setOpen] = useState(false)
  const [key, setKey] = useState(() => localStorage.getItem(STORAGE_KEY) ?? '')

  useEffect(() => {
    const show = () => setOpen(true)
    window.addEventListener('memoryledger-auth-required', show)
    return () => window.removeEventListener('memoryledger-auth-required', show)
  }, [])

  if (!open) return null
  return (
    <div className="api-key-prompt" role="dialog" aria-modal="true" aria-label="API key required">
      <form onSubmit={(event) => {
        event.preventDefault()
        localStorage.setItem(STORAGE_KEY, key.trim())
        setOpen(false)
        window.location.reload()
      }}>
        <strong>API key required</strong>
        <span>Enter the key supplied by your MemoryLedger operator.</span>
        <input type="password" value={key} onChange={(event) => setKey(event.target.value)} autoFocus />
        <button type="submit" disabled={!key.trim()}>Continue</button>
      </form>
    </div>
  )
}
