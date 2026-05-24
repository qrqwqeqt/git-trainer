import '@testing-library/jest-dom/vitest'
import { afterEach } from 'vitest'
import { cleanup } from '@testing-library/react'

// RTL без globals не чистить DOM автоматично — робимо це вручну.
afterEach(() => {
  cleanup()
})
