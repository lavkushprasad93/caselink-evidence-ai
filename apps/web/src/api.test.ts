import { afterEach, describe, expect, it, vi } from 'vitest'
import { getHealth } from './api'

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('getHealth', () => {
  it('returns a valid API health response', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(
        new Response(JSON.stringify({ status: 'ok', version: '0.1.0' }), {
          status: 200,
          headers: { 'Content-Type': 'application/json' },
        }),
      ),
    )

    await expect(getHealth()).resolves.toEqual({ status: 'ok', version: '0.1.0' })
  })

  it('reports an invalid health response', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(
        new Response(JSON.stringify({ status: 'error' }), {
          status: 200,
          headers: { 'Content-Type': 'application/json' },
        }),
      ),
    )

    await expect(getHealth()).rejects.toThrow('API returned an invalid health response')
  })
})
