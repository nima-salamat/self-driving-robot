"""Optional session-based authentication for the Stream dashboard.

Credentials are read from STREAM_USERNAME / STREAM_PASSWORD in the process
environment, with python/.env as a local fallback. The .env file is deliberately
parsed here so Stream does not require an additional runtime dependency.
"""
import hmac
import ipaddress
import os
import re
import secrets
import threading
import time
from datetime import timedelta
from pathlib import Path
from urllib.parse import urlsplit

from flask import jsonify, redirect, render_template, request, session, url_for


_ENV_KEY = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_UNSAFE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}
_LOGIN_WINDOW_SECONDS = 60.0
_LOGIN_MAX_FAILURES = 5


def _load_env_file(path, environ):
    """Load simple KEY=VALUE entries without overriding process environment."""
    env_path = Path(path)
    try:
        handle = env_path.open("r", encoding="utf-8")
    except FileNotFoundError:
        return
    except OSError as exc:
        raise RuntimeError(f"cannot read Stream environment file {env_path}: {exc}") from exc

    with handle:
        for raw_line in handle:
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith("export "):
                line = line[7:].lstrip()
            key, separator, value = line.partition("=")
            key = key.strip()
            if not separator or not _ENV_KEY.fullmatch(key) or key in environ:
                continue
            value = value.strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
                value = value[1:-1]
            environ[key] = value


def load_stream_credentials(env_file, environ=None):
    """Return optional Stream credentials and reject a partial configuration."""
    env = os.environ if environ is None else environ
    _load_env_file(env_file, env)
    username = env.get("STREAM_USERNAME")
    password = env.get("STREAM_PASSWORD")

    username_set = username is not None and username != ""
    password_set = password is not None and password != ""
    if not username_set and not password_set:
        return None, None
    if not username_set or not password_set:
        raise RuntimeError(
            "Stream authentication configuration is incomplete: set both "
            "STREAM_USERNAME and STREAM_PASSWORD, or leave both unset."
        )
    return str(username), str(password)


class StreamAuthMixin:
    """Shared authentication guard and login/logout endpoints."""

    def _initialize_stream_auth(self, env_file):
        self._auth_username, self._auth_password = load_stream_credentials(env_file)
        self.auth_enabled = self._auth_username is not None

        # The dashboard exposes live telemetry and (unless configured read-only)
        # robot controls. Never publish it on a non-loopback interface without
        # an explicit login configuration.
        bind_host = str(getattr(self.config, "STREAM_HOST", None) or "127.0.0.1").strip()
        normalized_host = bind_host[1:-1] if bind_host.startswith("[") and bind_host.endswith("]") else bind_host
        if normalized_host.lower() != "localhost":
            try:
                loopback_only = ipaddress.ip_address(normalized_host).is_loopback
            except ValueError:
                # DNS names and wildcard/interface names cannot be assumed local.
                loopback_only = False
        else:
            loopback_only = True
        if not self.auth_enabled and not loopback_only:
            raise RuntimeError(
                "Stream dashboard is bound to a non-loopback interface "
                f"({bind_host!r}) but authentication is not configured. "
                "Set both STREAM_USERNAME and STREAM_PASSWORD, or bind locally "
                "with --stream-host 127.0.0.1."
            )

        self._auth_login_attempts = {}
        self._auth_login_lock = threading.Lock()

        # A random per-process key means old login cookies become invalid after
        # restart. It is never written to disk or included in the dashboard.
        self.app.secret_key = secrets.token_urlsafe(48)
        self.app.config.update(
            SESSION_COOKIE_HTTPONLY=True,
            SESSION_COOKIE_SAMESITE="Lax",
            SESSION_COOKIE_SECURE=os.environ.get("STREAM_COOKIE_SECURE", "").strip().lower()
            in {"1", "true", "yes", "on"},
            PERMANENT_SESSION_LIFETIME=timedelta(hours=12),
            SESSION_REFRESH_EACH_REQUEST=True,
        )

    def _same_origin_error(self):
        """Reject browser state changes originating from another site."""
        origin = request.headers.get("Origin")
        source = origin or request.headers.get("Referer")
        if source:
            parsed = urlsplit(source)
            if (
                parsed.scheme in {"http", "https"}
                and parsed.netloc
                and parsed.netloc.lower() == request.host.lower()
            ):
                return None
        return jsonify(
            success=False,
            message="state-changing Stream requests must originate from this dashboard",
        ), 403

    def _authentication_guard(self):
        if not self.auth_enabled:
            return None

        # Static JS/CSS has no private runtime data; it is needed by the login
        # and dashboard pages and carries no dashboard control functionality.
        if request.endpoint == "static":
            return None

        if request.endpoint == "stream_login":
            if request.method in _UNSAFE_METHODS:
                return self._same_origin_error()
            return None

        if not session.get("stream_authenticated"):
            if request.method == "GET" and request.path in {"/", "/encoder-map"}:
                return redirect(url_for("stream_login"))
            return jsonify(
                success=False,
                message="authentication required",
                login_url=url_for("stream_login"),
            ), 401

        if request.method in _UNSAFE_METHODS:
            return self._same_origin_error()
        return None

    def _auth_response_headers(self, response):
        # The dashboard contains live robot state and must not be cached by
        # browsers or intermediary proxies.
        response.headers.setdefault("Cache-Control", "no-store")
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "same-origin")
        return response

    def _login_attempt_is_limited(self, client_ip):
        now = time.monotonic()
        with self._auth_login_lock:
            recent = [
                stamp for stamp in self._auth_login_attempts.get(client_ip, [])
                if now - stamp < _LOGIN_WINDOW_SECONDS
            ]
            if recent:
                self._auth_login_attempts[client_ip] = recent
            else:
                self._auth_login_attempts.pop(client_ip, None)
            return len(recent) >= _LOGIN_MAX_FAILURES

    def _record_login_failure(self, client_ip):
        now = time.monotonic()
        with self._auth_login_lock:
            recent = [
                stamp for stamp in self._auth_login_attempts.get(client_ip, [])
                if now - stamp < _LOGIN_WINDOW_SECONDS
            ]
            recent.append(now)
            self._auth_login_attempts[client_ip] = recent
            return len(recent) >= _LOGIN_MAX_FAILURES

    def stream_login(self):
        if not self.auth_enabled:
            return redirect(url_for("index"))
        if session.get("stream_authenticated"):
            return redirect(url_for("index"))
        if request.method == "GET":
            response = render_template("stream_login.html", error=None)
            return response

        client_ip = str(request.remote_addr or "unknown")
        if self._login_attempt_is_limited(client_ip):
            return render_template(
                "stream_login.html",
                error="Too many failed attempts. Wait one minute and try again.",
            ), 429

        candidate_username = request.form.get("username", "")
        candidate_password = request.form.get("password", "")
        username_matches = hmac.compare_digest(
            candidate_username.encode("utf-8"),
            self._auth_username.encode("utf-8"),
        )
        password_matches = hmac.compare_digest(
            candidate_password.encode("utf-8"),
            self._auth_password.encode("utf-8"),
        )
        if not (username_matches and password_matches):
            limited = self._record_login_failure(client_ip)
            error = (
                "Too many failed attempts. Wait one minute and try again."
                if limited else "Invalid username or password."
            )
            return render_template("stream_login.html", error=error), 429 if limited else 401

        with self._auth_login_lock:
            self._auth_login_attempts.pop(client_ip, None)
        session.clear()
        session.permanent = True
        session["stream_authenticated"] = True
        return redirect(url_for("index"))

    def stream_logout(self):
        session.clear()
        return redirect(url_for("stream_login"))

    def _register_auth_routes(self):
        self.app.add_url_rule(
            "/login", "stream_login", self.stream_login, methods=["GET", "POST"]
        )
        self.app.add_url_rule(
            "/logout", "stream_logout", self.stream_logout, methods=["POST"]
        )
        self.app.before_request(self._authentication_guard)
        self.app.after_request(self._auth_response_headers)


def register_auth_routes(app, streamer):
    """Register authentication routes and the shared request guard."""
    streamer._register_auth_routes()
