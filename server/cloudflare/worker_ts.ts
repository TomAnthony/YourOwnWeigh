/** Cloudflare entrypoint for the same application served by server/ts/local.ts. */
import { handleApp } from "../ts/app.ts";
import { captureWithings, firmwareOffer } from "../ts/withings_capture.ts";

export { BridgeDurableObject } from "./bridge_do.ts";

interface Env {
  YOW_BRIDGE?: DurableObjectNamespace;
  DB: D1Database;
  ALLOW_HTTP_SCALE?: string;
  YOW_BOOTSTRAP_TOKEN?: string;
  ASSETS?: { fetch(request: Request): Promise<Response> };
}

export default {
  async fetch(request: Request, env: Env): Promise<Response> {
    const sanitized = new Headers(request.headers);
    sanitized.delete("X-YOW-Peer-IP");
    request = new Request(request, { headers: sanitized });
    const response = await handleApp(request, {
      ...env,
      ALLOW_HTTP_SCALE: true,
      bridgeRequest: (request, adminId) => {
        if (!env.YOW_BRIDGE)
          return Promise.resolve(
            new Response("Bridge binding missing", { status: 503 }),
          );
        const headers = new Headers(request.headers);
        headers.delete("X-YOW-Authenticated-Admin");
        if (adminId) headers.set("X-YOW-Authenticated-Admin", adminId);
        return env.YOW_BRIDGE.get(env.YOW_BRIDGE.idFromName("household")).fetch(
          new Request(request, { headers }),
        );
      },
      captureWithings: captureWithings,
      lookupFirmwareOffer: firmwareOffer,
    });
    if (new URL(request.url).protocol !== "https:" || response.status === 101)
      return response;
    const headers = new Headers(response.headers);
    headers.set("Strict-Transport-Security", "max-age=31536000");
    return new Response(response.body, {
      status: response.status,
      statusText: response.statusText,
      headers,
    });
  },
};
