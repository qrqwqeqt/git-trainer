import { beforeEach, describe, expect, it } from 'vitest'

import { useGitStore } from './gitStore'

beforeEach(() => {
  useGitStore.getState().reset()
})

describe('gitStore.applyMessage', () => {
  it('GRAPH_UPDATE replaces the graph', () => {
    const graph = {
      nodes: [{ id: 'abc', branch: 'main', parents: [] }],
      edges: [],
    }
    useGitStore.getState().applyMessage({ type: 'GRAPH_UPDATE', graph })
    expect(useGitStore.getState().graph.nodes).toHaveLength(1)
    expect(useGitStore.getState().graph.nodes[0].id).toBe('abc')
  })

  it('USER_JOINED adds a user and an event', () => {
    useGitStore
      .getState()
      .applyMessage({ type: 'USER_JOINED', userId: 'u1', username: 'dzhe' })
    const s = useGitStore.getState()
    expect(s.users.u1).toEqual({ id: 'u1', username: 'dzhe' })
    expect(s.events.at(-1)?.kind).toBe('user-join')
  })

  it('USER_LEFT removes the user', () => {
    const st = useGitStore.getState()
    st.applyMessage({ type: 'USER_JOINED', userId: 'u1', username: 'dzhe' })
    st.applyMessage({ type: 'USER_LEFT', userId: 'u1' })
    expect(useGitStore.getState().users.u1).toBeUndefined()
  })

  it('GIT_EVENT appends a git event with stdout/exit', () => {
    useGitStore.getState().applyMessage({
      type: 'GIT_EVENT',
      action: 'commit',
      userId: 'u1',
      payload: {
        command: 'git commit -m x',
        argv: ['git', 'commit', '-m', 'x'],
        exit_code: 0,
        stdout: '[main abc] x',
        stderr: '',
      },
    })
    const ev = useGitStore.getState().events.at(-1)
    expect(ev?.kind).toBe('git')
    if (ev?.kind === 'git') {
      expect(ev.command).toBe('git commit -m x')
      expect(ev.exitCode).toBe(0)
      expect(ev.stdout).toBe('[main abc] x')
    }
  })

  it('ERROR appends an error event', () => {
    useGitStore.getState().applyMessage({
      type: 'ERROR',
      payload: { reason: 'rate_limited', detail: 'too fast' },
    })
    const ev = useGitStore.getState().events.at(-1)
    expect(ev?.kind).toBe('error')
    if (ev?.kind === 'error') {
      expect(ev.reason).toBe('rate_limited')
    }
  })

  it('reset clears graph, events and users', () => {
    const st = useGitStore.getState()
    st.applyMessage({ type: 'USER_JOINED', userId: 'u1', username: 'd' })
    st.reset()
    const s = useGitStore.getState()
    expect(s.events).toHaveLength(0)
    expect(Object.keys(s.users)).toHaveLength(0)
    expect(s.graph.nodes).toHaveLength(0)
  })
})
