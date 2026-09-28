import type { NextApiRequest, NextApiResponse } from 'next';

export const config = {
  api: {
    responseLimit: false,
  },
};

export default async function handler(req: NextApiRequest, res: NextApiResponse) {
  if (req.method !== 'POST') {
    res.setHeader('Allow', 'POST');
    res.status(405).end();
    return;
  }

  const proxyTarget = (process.env.API_PROXY_TARGET || 'http://127.0.0.1:5670').replace(/\/+$/, '');
  const controller = new AbortController();
  const abortUpstream = () => {
    controller.abort();
  };
  const abortIfClientDisconnected = () => {
    if (!res.writableEnded) abortUpstream();
  };

  req.on('aborted', abortUpstream);
  res.on('close', abortIfClientDisconnected);
  res.socket?.on('close', abortIfClientDisconnected);

  let heartbeat: ReturnType<typeof setInterval> | undefined;
  try {
    const contentType = req.headers['content-type'];
    const headers: Record<string, string> = {
      'content-type': typeof contentType === 'string' ? contentType : 'application/json',
    };
    if (typeof req.headers.authorization === 'string') {
      headers.authorization = req.headers.authorization;
    }
    if (typeof req.headers.cookie === 'string') {
      headers.cookie = req.headers.cookie;
    }

    const upstream = await fetch(`${proxyTarget}/api/v1/chat/react-agent`, {
      method: 'POST',
      headers,
      body: JSON.stringify(req.body),
      signal: controller.signal,
    });

    res.statusCode = upstream.status;
    res.setHeader('Content-Type', upstream.headers.get('content-type') || 'text/event-stream');
    res.setHeader('Cache-Control', upstream.headers.get('cache-control') || 'no-cache');
    res.setHeader('X-Accel-Buffering', 'no');
    res.flushHeaders();

    // Keep the browser-facing stream alive while the model is silent during a
    // long prompt prefill or local CPU inference. SSE comments are ignored by
    // the event parser but reset idle timeouts in browsers and reverse proxies.
    heartbeat = setInterval(() => {
      if (!res.destroyed && !res.writableEnded) {
        res.write(': keep-alive\n\n');
      }
    }, 15_000);
    heartbeat.unref?.();

    if (!upstream.body) {
      res.end();
      return;
    }

    const reader = upstream.body.getReader();
    let result: ReadableStreamReadResult<Uint8Array>;
    do {
      result = await reader.read();
      if (!result.done && !res.write(Buffer.from(result.value))) {
        await new Promise<void>(resolve => {
          const finishWaiting = () => {
            res.off('drain', finishWaiting);
            res.off('close', finishWaiting);
            resolve();
          };
          res.once('drain', finishWaiting);
          res.once('close', finishWaiting);
          if (res.destroyed) finishWaiting();
        });
      }
    } while (!result.done);
    res.end();
  } catch {
    if (controller.signal.aborted) return;
    if (!res.headersSent) {
      res.status(502).json({ error: 'Agent stream proxy failed' });
    } else if (!res.writableEnded) {
      res.end();
    }
  } finally {
    if (heartbeat) clearInterval(heartbeat);
    req.off('aborted', abortUpstream);
    res.off('close', abortIfClientDisconnected);
    res.socket?.off('close', abortIfClientDisconnected);
  }
}
