"""Firmware-offer protocol and failure tests; synthetic credentials, no network."""

from contextlib import redirect_stderr, redirect_stdout
import hashlib
import io
import json
import ssl
import unittest
from unittest.mock import Mock, patch
import urllib.error
import urllib.parse
import urllib.request

import probe_withings_firmware as probe


MAC = "02:00:00:00:00:01"
SECRET = "0123456789ABCDEF"
URL = "https://cdnfw.withings.net/example/stock.bin"
SHA1 = "A1" * 20


def arguments(*extra):
    return probe.parse_args(["--mac", "02-00-00-00-00-01", *extra])


def response(document, raw=None):
    result = Mock()
    result.status = 200
    result.read.return_value = json.dumps(document).encode() if raw is None else raw
    result.__enter__ = Mock(return_value=result)
    result.__exit__ = Mock(return_value=False)
    return result


def client_with(*responses):
    log = []
    client = probe.WithingsClient(arguments(), report=log.append)
    client.opener = Mock()
    client.opener.open.side_effect = list(responses)
    return client, log


class FirmwareProbeTests(unittest.TestCase):
    def test_wbs06_profile_and_offer_without_private_output(self):
        client, log = client_with(
            response({"status": 0, "body": {"once": "test-challenge"}}),
            response({"status": 0, "body": {
                "sessionid": "private-session", "sp": {"users": ["private-user"]},
                "syp": {"blc": URL, "sha1": SHA1},
            }}),
        )
        result = probe.lookup(arguments(), SECRET, client)
        self.assertEqual(result, {"offered": True, "url": URL, "sha1": SHA1.lower()})
        calls = client.opener.open.call_args_list
        self.assertEqual(len(calls), 2)
        once, session = [call.args[0] for call in calls]
        self.assertEqual(once.data, b"action=get")
        self.assertEqual(once.full_url, "https://scalews.withings.net/once?appliver=1181&appname=WBS06&apppfm=device")
        fields = urllib.parse.parse_qs(session.data.decode())
        self.assertEqual(fields, {key: [str(value)] for key, value in {
            "action": "new", "auth": MAC,
            "hash": hashlib.sha256(f"{MAC}:{SECRET}:test-challenge".encode()).hexdigest(),
            "mfgid": 0, "currentfw": 1181, "batterylvl": 100, "duration": 300,
            "wstarget": 1, "enrich": "t", "trademark": 1, "network": 1,
            "hashmethod": "sha256", "trigger": "weather", "withaccids": 1, "feature_mask": 0,
        }.items()})
        self.assertEqual(log, ["/once: HTTP 200, Withings status 0", "/session: HTTP 200, Withings status 0"])

    def test_wbs13_profile_includes_model_fields_but_never_finalizes_setup(self):
        args = arguments("--model", "WBS13", "--mfgid", "0x012345", "--feature-mask", "0x10")
        client, _ = client_with(
            response({"status": 0, "body": {"once": "nonce"}}),
            response({"status": 0, "body": {"syp": {"utc": 123}}}),
        )
        fields = probe.session_fields(args, SECRET, "nonce")
        self.assertEqual(fields["duration"], 600)
        self.assertEqual(fields["httpslink"], 2)
        self.assertEqual(fields["trigger"], "weather,ds")
        self.assertEqual(fields["mfgid"], 0x012345)
        self.assertEqual(fields["feature_mask"], 16)
        self.assertEqual(fields["currentfw"], 1311)
        self.assertNotIn("final", fields)
        real_client = probe.WithingsClient(args)
        self.assertEqual(real_client.query, "appliver=1311&appname=WBS13&apppfm=device")
        self.assertEqual(probe.lookup(args, SECRET, client), {"offered": False})

    def test_ws30_uses_wbs03_query_and_stock_version(self):
        args = arguments("--model", "WBS03")
        client = probe.WithingsClient(args, report=lambda _: None)
        client.opener = Mock()
        client.opener.open.side_effect = [
            response({"status": 0, "body": {"once": "n"}}),
            response({"status": 0, "body": {"syp": {"blc": URL, "sha1": SHA1}}}),
        ]
        self.assertEqual(probe.lookup(args, SECRET, client), {"offered": True, "url": URL, "sha1": SHA1.lower()})
        requests = [call.args[0] for call in client.opener.open.call_args_list]
        for request in requests:
            self.assertIn("appliver=921&appname=WBS03&apppfm=device", request.full_url)
        fields = urllib.parse.parse_qs(requests[1].data.decode())
        self.assertEqual(fields["currentfw"], ["921"])
        self.assertEqual(fields["duration"], ["300"])
        self.assertEqual(fields["mfgid"], ["0"])
        self.assertEqual(fields["trigger"], ["weather"])
        self.assertNotIn("httpslink", fields)
        self.assertNotIn("final", fields)

    def test_missing_offer_is_distinct_from_invalid_offer(self):
        for body in ({}, {"syp": {}}, {"syp": {"blc": None, "sha1": None}}):
            with self.subTest(body=body):
                client = Mock()
                client.post.side_effect = [{"once": "n"}, body]
                self.assertEqual(probe.lookup(arguments(), SECRET, client), {"offered": False})
        for syp in ([], {"blc": URL}, {"sha1": SHA1}, {"blc": URL, "sha1": "broken"},
                    {"blc": "https://other.example/test.bin", "sha1": SHA1},
                    {"blc": "https://user:pass@cdnfw.withings.net/test.bin", "sha1": SHA1},
                    {"blc": URL + "\n", "sha1": SHA1}):
            with self.subTest(syp=syp), self.assertRaises(probe.ProbeError):
                client = Mock()
                client.post.side_effect = [{"once": "n"}, {"syp": syp}]
                probe.lookup(arguments(), SECRET, client)

    def test_bad_challenge_never_sends_authentication(self):
        for nonce in (None, "", "x" * 32, 1, {}):
            with self.subTest(nonce=nonce), self.assertRaisesRegex(probe.ProbeError, "invalid challenge"):
                client = Mock()
                client.post.return_value = {"once": nonce}
                try:
                    probe.lookup(arguments(), SECRET, client)
                finally:
                    self.assertEqual(client.post.call_count, 1)

    def test_application_rejection_reports_status_without_error_body(self):
        client, log = client_with(response({"status": 401, "error": SECRET, "body": {"once": "n"}}))
        with self.assertRaisesRegex(probe.ProbeError, "status 401.*offer unknown"):
            probe.lookup(arguments(), SECRET, client)
        self.assertEqual(log, ["/once: HTTP 200, Withings status 401"])
        self.assertEqual(client.opener.open.call_count, 1)
        client, _ = client_with(
            response({"status": 0, "body": {"once": "n"}}),
            response({"status": 255, "body": {"syp": {"blc": URL, "sha1": SHA1}}}),
        )
        with self.assertRaisesRegex(probe.ProbeError, "/session:.*status 255"):
            probe.lookup(arguments(), SECRET, client)

    def test_http_rejection_and_redirect_are_not_no_offer(self):
        for code in (403, 302, 307, 308):
            with self.subTest(code=code):
                error = urllib.error.HTTPError("https://example.test", code, "error", {}, io.BytesIO(b"private body"))
                client, _ = client_with(error)
                with self.assertRaisesRegex(probe.ProbeError, f"HTTP {code}.*offer unknown"):
                    client.post("once", {"action": "get"})
                self.assertEqual(client.opener.open.call_count, 1)
        request = urllib.request.Request("https://example.test", data=b"private")
        self.assertIsNone(probe.NoRedirects().redirect_request(request, None, 302, "", {}, "https://other.test"))

    def test_client_certificate_requirement_is_distinguished_from_other_status_100_errors(self):
        for message, expected in (
            ("Client certificate is required for this device", "requires this device's TLS client certificate"),
            ("Client certificate is required for this device " + SECRET, None),
            (SECRET, None),
        ):
            with self.subTest(expected=expected):
                client, log = client_with(response({"status": 100, "body": {}, "error": message}))
                with self.assertRaises(probe.ProbeError) as caught:
                    client.post("session", {})
                text = str(caught.exception)
                self.assertIn("status 100", text)
                self.assertNotIn(SECRET, text)
                self.assertNotIn(SECRET, "\n".join(log))
                if expected:
                    self.assertIn(expected, text)
                    self.assertIn("--client-cert and --client-key", text)
                else:
                    self.assertNotIn("client certificate", text)

    def test_tls_and_timeout_are_diagnosed_separately(self):
        cert_error = ssl.SSLCertVerificationError(1, "verification failed")
        cert_error.verify_message = "certificate verify failed"
        for reason, message in ((cert_error, "TLS certificate verification failed"),
                                (ssl.SSLError(1, "handshake failed"), "TLS failed"),
                                (TimeoutError(), "request timed out")):
            with self.subTest(message=message):
                client, _ = client_with(urllib.error.URLError(reason))
                with self.assertRaisesRegex(probe.ProbeError, message):
                    client.post("once", {"action": "get"})

    def test_malformed_and_oversized_responses(self):
        for data in (b"<html>not JSON</html>", b"[]", b"{}", b'{"status":false}',
                     b'{"status":0,"body":[]}', b"x" * (probe.MAX_RESPONSE + 1)):
            with self.subTest(size=len(data)):
                wire_response = response(None, raw=data)
                client, _ = client_with(wire_response)
                with self.assertRaises(probe.ProbeError):
                    client.post("once", {"action": "get"})
                wire_response.read.assert_called_once_with(probe.MAX_RESPONSE + 1)

    def test_tls_options_keep_certificate_verification(self):
        with patch.object(probe.ssl, "create_default_context") as create, \
                patch.object(probe.urllib.request, "HTTPSHandler") as handler, \
                patch.object(probe.urllib.request, "build_opener"):
            args = arguments("--ca-file", "ca.pem", "--client-cert", "cert.pem", "--client-key", "key.pem")
            probe.WithingsClient(args)
            create.assert_called_once_with(cafile="ca.pem")
            create.return_value.load_cert_chain.assert_called_once_with("cert.pem", "key.pem")
            handler.assert_called_once_with(context=create.return_value)

    def test_cli_rejects_invalid_metadata_before_network(self):
        for extra in (("--model", "WBS13"), ("--current-fw", "65536"), ("--mfgid", "-1"),
                      ("--feature-mask", "0x100000000"), ("--battery-level", "101"),
                      ("--timeout", "nan"), ("--timeout", "-1"), ("--client-key", "key.pem"),
                      ("--host", "https://scalews.withings.net"), ("--host", "a@b")):
            with self.subTest(extra=extra), redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as caught:
                arguments(*extra)
            self.assertEqual(caught.exception.code, 2)

    def test_cli_secret_prompt_environment_and_exit_codes(self):
        for secret_args in ([], ["--secret", SECRET], ["--secret-env", "YOW_TEST_SECRET"]):
            output = io.StringIO()
            with patch.object(probe.getpass, "getpass", return_value=SECRET), patch.dict(probe.os.environ, {"YOW_TEST_SECRET": SECRET}), \
                    patch.object(probe, "WithingsClient"), patch.object(probe, "lookup", return_value={"offered": False}) as lookup, \
                    redirect_stdout(output):
                self.assertEqual(probe.main(["--mac", MAC, *secret_args]), 0)
                self.assertEqual(lookup.call_args.args[1], SECRET)
            self.assertNotIn(SECRET, output.getvalue())
        with patch.object(probe, "WithingsClient") as client, redirect_stderr(io.StringIO()):
            self.assertEqual(probe.main(["--mac", MAC, "--secret", "a" * 48]), 1)
            client.assert_not_called()
        with patch.object(probe, "WithingsClient", side_effect=probe.ProbeError("/session: rejected")), \
                redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            self.assertEqual(probe.main(["--mac", MAC, "--secret", SECRET]), 1)


if __name__ == "__main__":
    unittest.main()
