import { JsonRpcGatewayClient, type WebSocketLike } from '@hermes/shared'
import { expect, it } from 'vitest'

function openSocket(onUrl: (url: string) => void): (url: string) => WebSocketLike {
  return url => {
    onUrl(url)
    const listeners = new Map<string, EventListener>()
    const socket = {
      readyState: WebSocket.CONNECTING,
      addEventListener(type: string, listener: EventListener) {
        listeners.set(type, listener)
        if (type === 'open') {
          queueMicrotask(() => {
            Object.assign(socket, { readyState: WebSocket.OPEN })
            listener(new Event('open'))
          })
        }
      },
      removeEventListener(type: string) {
        listeners.delete(type)
      },
      close() {},
      send() {}
    }
    return socket as unknown as WebSocketLike
  }
}

it('adds only the configured observer surface to a credentialed gateway URL', async () => {
  let captured = ''
  const client = new JsonRpcGatewayClient({
    observerSurface: 'desktop',
    socketFactory: openSocket(url => {
      captured = url
    })
  })

  await client.connect('wss://gateway.example/api/ws?ticket=secret-ticket')

  const url = new URL(captured)
  expect(url.searchParams.get('surface')).toBe('desktop')
  expect(url.searchParams.get('ticket')).toBe('secret-ticket')
  expect([...url.searchParams.keys()].sort()).toEqual(['surface', 'ticket'])
})
