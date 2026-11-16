"""Signed gateway token for signed-in users.

The ingress gateway (Istio RequestAuthentication + a DENY AuthorizationPolicy,
see hazel-fluxcd) only lets /api/ and /search through with a valid RS256 JWT
in the GATE_JWT_COOKIE cookie, signed by this instance's key, for this host.
Unlike a bare session-cookie check at the gateway, that can't be forged
without the private key, and the gateway verifies it without calling Django.

Django stays the authority on permissions; this is defence in depth.

Without GATE_JWT_PRIVATE_KEY (local development) the middleware is disabled.
"""

import time

import jwt
from cryptography.hazmat.primitives import serialization
from django.conf import settings
from django.core.exceptions import MiddlewareNotUsed

ALGORITHM = "RS256"


def load_private_key(pem):
    return serialization.load_pem_private_key(pem.encode(), password=None)


def issue(private_key, kid, issuer, audience, subject, ttl, now=None):
    now = int(now if now is not None else time.time())
    claims = {
        "iss": issuer,
        "aud": audience,
        "sub": subject,
        "iat": now,
        "exp": now + ttl,
    }
    return jwt.encode(claims, private_key, algorithm=ALGORITHM, headers={"kid": kid})


def needs_reissue(token, public_key, issuer, audience, subject, refresh_below, now=None):
    """True unless token is valid for this user and has refresh_below+ seconds left."""
    if not token:
        return True
    now = time.time() if now is None else now
    try:
        claims = jwt.decode(
            token,
            public_key,
            algorithms=[ALGORITHM],
            issuer=issuer,
            audience=audience,
            options={"require": ["exp", "iss", "aud", "sub"]},
        )
    except jwt.PyJWTError:
        return True
    return claims["sub"] != subject or claims["exp"] - now < refresh_below


def is_signed_in(user):
    # Arches' SetAnonymousUser swaps AnonymousUser for a real "anonymous"
    # User row, which has is_authenticated == True.
    return (
        user is not None
        and user.is_authenticated
        and user.username != "anonymous"
    )


class GateTokenMiddleware:
    def __init__(self, get_response):
        pem = getattr(settings, "GATE_JWT_PRIVATE_KEY", None)
        if not pem:
            raise MiddlewareNotUsed("GATE_JWT_PRIVATE_KEY not set")
        self.get_response = get_response
        self.private_key = load_private_key(pem)
        self.public_key = self.private_key.public_key()
        self.issuer = settings.GATE_JWT_ISSUER
        self.kid = settings.GATE_JWT_KID
        self.ttl = settings.GATE_JWT_TTL
        self.cookie = settings.GATE_JWT_COOKIE
        self.secure = settings.GATE_JWT_SECURE

    def __call__(self, request):
        response = self.get_response(request)
        user = getattr(request, "user", None)
        current = request.COOKIES.get(self.cookie)
        if is_signed_in(user):
            audience = request.get_host().split(":")[0]
            subject = str(user.pk)
            # Reissue once a third of the lifetime has gone, so an active
            # user never presents an expired token to the gateway
            if needs_reissue(
                current, self.public_key, self.issuer, audience, subject, self.ttl * 2 // 3
            ):
                token = issue(
                    self.private_key, self.kid, self.issuer, audience, subject, self.ttl
                )
                response.set_cookie(
                    self.cookie,
                    token,
                    # Expire the cookie before the token: the gateway answers
                    # 401 to every path on the host for an expired token
                    max_age=max(self.ttl - 60, 60),
                    secure=self.secure,
                    httponly=True,
                    samesite="Lax",
                )
        elif current:
            response.delete_cookie(self.cookie, samesite="Lax")
        return response
