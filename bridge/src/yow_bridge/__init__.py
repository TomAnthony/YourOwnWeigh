"""YourOwnWeigh Bluetooth bridge. Vendor imports belong to the server."""

__version__ = "0.4.1"
BRIDGE_PROTOCOL = "yow.bridge"

# Use our product identity on HTTP and WebSocket requests. Cloudflare can reject
# urllib's default Python-urllib header before requests reach the Worker.
USER_AGENT = f"YourOwnWeigh/{__version__}"
