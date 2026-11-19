import { useEffect, useState } from 'react'
import { getHealth, type Health } from './api'

export default function App() {
  const [health, setHealth] = useState<Health | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    getHealth()
      .then(setHealth)
      .catch((cause: Error) => setError(cause.message))
  }, [])

  return (
    <main className="mx-auto max-w-xl p-8">
      <h1 className="text-2xl font-semibold">CaseLink Evidence AI</h1>
      <p className="mt-1 text-slate-600">Every finding linked to its evidence.</p>

      <section className="mt-8 border-l-4 border-slate-300 pl-4" aria-live="polite">
        <h2 className="font-medium">API status</h2>
        {health && (
          <p className="text-green-700">Connected, version {health.version}</p>
        )}
        {error && (
          <p className="text-red-700">
            Can&apos;t reach the API ({error}). Start it with: uvicorn app.main:app --port 8000
          </p>
        )}
        {!health && !error && <p className="text-slate-500">Checking…</p>}
      </section>
    </main>
  )
}
