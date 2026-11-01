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
speaks plain HTTP. Expose only 443; never forward port 80 to the internet. A
scale on the LAN may instead use the host's IP over HTTP.

## Run

```sh
cp .env.example .env     # set YOW_PUBLIC_ORIGIN to your https origin
mkdir -p data
docker compose up -d
```

The image (`ghcr.io/tomanthony/yourownweigh`) is built by the repo's CI;
uncomment `build:` in the compose to build it yourself.
Read the first-run bootstrap token with `docker logs yourownweigh`, open your
dashboard URL and set an admin password. To migrate an instance, drop its DB in
`data/yow.sqlite3` before the first start.

## Reverse proxy

Forward your subdomain to `127.0.0.1:8080`, preserving the `Host` header (it
must match `YOW_PUBLIC_ORIGIN`) and the WebSocket upgrade (the bridge pairs over
it). The server only accepts that Host, so it is reachable only through the proxy.

## Point the scale at it

In the bridge's **Firmware Bridge → Configure**, set the server host to your
subdomain over `https` (or the host's LAN IP over `http`).

## Update

`docker compose pull && docker compose up -d`.
