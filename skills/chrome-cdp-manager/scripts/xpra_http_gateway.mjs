#!/usr/bin/env node

import fs from "node:fs";
import http from "node:http";
import net from "node:net";

function option(name, fallback) {
  const index = process.argv.indexOf(name);
  return index >= 0 && index + 1 < process.argv.length ? process.argv[index + 1] : fallback;
}

const listenHost = option("--listen-host", "0.0.0.0");
const listenPort = Number(option("--listen-port", "14500"));
const backendHost = option("--backend-host", "127.0.0.1");
const backendPort = Number(option("--backend-port", "14501"));
const pidFile = option("--pid-file");

function requestPath(rawTarget) {
  if (!/^https?:\/\//i.test(rawTarget))
    return rawTarget || "/";
  const parsed = new URL(rawTarget);
  return `${parsed.pathname}${parsed.search}`;
}

const server = http.createServer((request, response) => {
  const headers = { ...request.headers, host: `${backendHost}:${backendPort}` };
  delete headers["proxy-connection"];
  const upstream = http.request({
    host: backendHost,
    port: backendPort,
    method: request.method,
    path: requestPath(request.url),
    headers,
  }, upstreamResponse => {
    response.writeHead(upstreamResponse.statusCode || 502, upstreamResponse.headers);
    upstreamResponse.pipe(response);
  });
  upstream.on("error", error => {
    if (!response.headersSent)
      response.writeHead(502, { "content-type": "text/plain" });
    response.end(`Xpra backend unavailable: ${error.code || error.message}\n`);
  });
  request.pipe(upstream);
});

server.on("upgrade", (request, socket, head) => {
  const upstream = net.connect(backendPort, backendHost, () => {
    const headers = { ...request.headers, host: `${backendHost}:${backendPort}` };
    delete headers["proxy-connection"];
    const lines = [`${request.method} ${requestPath(request.url)} HTTP/1.1`];
    for (const [name, value] of Object.entries(headers)) {
      if (Array.isArray(value)) {
        for (const item of value)
          lines.push(`${name}: ${item}`);
      } else if (value !== undefined) {
        lines.push(`${name}: ${value}`);
      }
    }
    upstream.write(`${lines.join("\r\n")}\r\n\r\n`);
    if (head.length)
      upstream.write(head);
    socket.pipe(upstream).pipe(socket);
  });
  upstream.on("error", () => socket.destroy());
  socket.on("error", () => upstream.destroy());
});

server.listen(listenPort, listenHost, () => {
  if (pidFile)
    fs.writeFileSync(pidFile, `${process.pid}\n`, { mode: 0o600 });
});

function shutdown() {
  server.close(() => process.exit(0));
  setTimeout(() => process.exit(1), 5000).unref();
}

process.on("SIGTERM", shutdown);
process.on("SIGINT", shutdown);
