import { beforeEach, describe, expect, it, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

import { Landing } from './Landing'

beforeEach(() => {
  localStorage.clear()
})

describe('Landing', () => {
  it('renders the brand and both fields', () => {
    render(<Landing prefillRoom={null} onEnter={vi.fn()} />)
    expect(screen.getByRole('heading', { name: 'Git Trainer' })).toBeTruthy()
    expect(screen.getByPlaceholderText('напр. dzhe')).toBeTruthy()
    expect(screen.getByPlaceholderText('напр. react basics')).toBeTruthy()
  })

  it('blocks submit and shows error when room is empty', async () => {
    const onEnter = vi.fn()
    render(<Landing prefillRoom={null} onEnter={onEnter} />)
    const user = userEvent.setup()

    await user.type(screen.getByPlaceholderText('напр. dzhe'), 'dzhe')
    await user.click(screen.getByRole('button'))

    expect(onEnter).not.toHaveBeenCalled()
    expect(screen.getByText(/Введи назву кімнати/i)).toBeTruthy()
  })

  it('generates a new roomId + label when creating a room', async () => {
    const onEnter = vi.fn()
    render(<Landing prefillRoom={null} onEnter={onEnter} />)
    const user = userEvent.setup()

    await user.type(screen.getByPlaceholderText('напр. dzhe'), 'dzhe')
    await user.type(screen.getByPlaceholderText('напр. react basics'), 'My Room')
    await user.click(screen.getByRole('button'))

    expect(onEnter).toHaveBeenCalledTimes(1)
    const arg = onEnter.mock.calls[0][0] as {
      roomId: string
      username: string
      label?: string
    }
    expect(arg.roomId).toMatch(/^my-room-[a-z0-9]{4}$/)
    expect(arg.username).toBe('dzhe')
    expect(arg.label).toBe('My Room')
  })

  it('joins a prefilled room without regenerating its id', async () => {
    const onEnter = vi.fn()
    render(<Landing prefillRoom="demo" onEnter={onEnter} />)
    const user = userEvent.setup()

    // кімната вже підставлена ('demo'); вводимо лише нік
    await user.type(screen.getByPlaceholderText('напр. dzhe'), 'dzhe')
    await user.click(screen.getByRole('button', { name: 'Увійти' }))

    expect(onEnter).toHaveBeenCalledTimes(1)
    expect(onEnter.mock.calls[0][0]).toEqual({ roomId: 'demo', username: 'dzhe' })
  })
})
