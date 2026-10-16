import { describe, expect, it } from 'vitest'
import { statusColor } from '../lib/api'

describe('statusColor', () => {
  it('maps success states', () => {
    expect(statusColor('succeeded')).toContain('emerald')
    expect(statusColor('ready')).toContain('emerald')
    expect(statusColor('approved')).toContain('emerald')
  })
  it('maps running states', () => {
    expect(statusColor('running')).toContain('amber')
    expect(statusColor('processing')).toContain('amber')
  })
  it('maps failure states', () => {
    expect(statusColor('failed')).toContain('rose')
    expect(statusColor('rejected')).toContain('rose')
  })
  it('maps pending states', () => {
    expect(statusColor('queued')).toContain('sky')
    expect(statusColor('pending')).toContain('sky')
  })
  it('falls back for unknown states', () => {
    expect(statusColor('mystery')).toContain('slate')
  })
})
