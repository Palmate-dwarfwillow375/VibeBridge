import { IS_PLATFORM } from '../../../constants/config';
import { getWsBase } from '../../../utils/api';
import type { ShellIncomingMessage, ShellOutgoingMessage } from '../types/types';

export function getShellWebSocketUrl(): string | null {
  const wsBase = getWsBase();

  if (IS_PLATFORM) {
    return `${wsBase}/shell`;
  }

  return `${wsBase}/shell`;
}

export function parseShellMessage(payload: string): ShellIncomingMessage | null {
  try {
    return JSON.parse(payload) as ShellIncomingMessage;
  } catch {
    return null;
  }
}

export function sendSocketMessage(ws: WebSocket | null, message: ShellOutgoingMessage): void {
  if (ws && ws.readyState === WebSocket.OPEN) {
    ws.send(JSON.stringify(message));
  }
}
