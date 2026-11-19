const apiBaseUrl = import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000'

export type Health = {
  status: 'ok'
  version: string
}

function isHealth(value: unknown): value is Health {
  return (
    typeof value === 'object' &&
    value !== null &&
    'status' in value &&
    value.status === 'ok' &&
    'version' in value &&
    typeof value.version === 'string'
  )
}

export async function getHealth(): Promise<Health> {
  const response = await fetch(`${apiBaseUrl}/health`)
  if (!response.ok) {
    throw new Error(`API returned HTTP ${response.status}`)
  }

  const payload: unknown = await response.json()
  if (!isHealth(payload)) {
    throw new Error('API returned an invalid health response')
  }
  return payload
}
