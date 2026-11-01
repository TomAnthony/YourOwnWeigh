# YourOwnWeigh in Docker

Run the server 24/7 on any Docker host behind your own reverse proxy. For the
components, flashing and scale setup see the [main README](../README.md); this
page covers only the container.

## How it is wired

```
Dashboard  --https :443-->  your reverse proxy  -->  container 127.0.0.1:8080
Scale      --https :443-->  (one subdomain)          (one plain-HTTP listener)
```

The proxy terminates TLS for one subdomain and forwards to the container, which
speaks plain HTTP. Expose only 443; never forward port 80 to the internet.

An HTTP-only scale (WS-30, or a Body Cardio before the HTTPS firmware) needs a
**LAN-only** port-80 route on your proxy that forwards to the same container and
uses the **same subdomain** as the `Host` header — the server only accepts the
host in `YOW_PUBLIC_ORIGIN`, so a raw LAN IP is rejected. Point the scale at the
subdomain (resolved to the proxy on your LAN), not at the IP.

## Run

```sh
cp .env.example .env            # set YOW_PUBLIC_ORIGIN to your https origin
mkdir -p data && chown 1000:1000 data   # the container runs as uid 1000 (node)
docker compose up -d
```

The container runs as the unprivileged `node` user (uid 1000), so the
bind-mounted `data/` must be writable by that uid — hence the `chown` above
(migrating an older root-owned `data/`? run the same chown once). The image
(`ghcr.io/tomanthony/yourownweigh`) is built by the repo's CI; to run your own
build instead, uncomment `build:` in the compose and start with
`docker compose up -d --build`.

Read the first-run bootstrap token with `docker logs yourownweigh`, open your
dashboard URL and set an admin password. To migrate an instance, drop its DB in
`data/yow.sqlite3` before the first start (and chown it to uid 1000).

## Reverse proxy

Forward your subdomain to `127.0.0.1:8080`, preserving the `Host` header (it
must match `YOW_PUBLIC_ORIGIN`), the WebSocket upgrade (the bridge pairs over
it), and `X-Forwarded-Proto` / `X-Forwarded-For` (the server uses them for the
request scheme and per-client login limits). The server only accepts that Host,
so it is reachable only through the proxy.

## Point the scale at it

In the bridge's **Firmware Bridge → Configure**, set the server host to your
subdomain — over `https` for an HTTPS scale, or over `http` for an HTTP-only
scale (via the LAN-only port-80 route above). Use the subdomain, not the LAN IP.

## Update

`docker compose pull && docker compose up -d`.
