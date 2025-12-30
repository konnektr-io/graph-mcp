# konnektr_mcp/auth.py
import httpx
from jose import jwt, JWTError
from mcp.server.auth.provider import AccessToken, TokenVerifier
from konnektr_mcp.config import get_settings

_jwks_cache: dict | None = None


async def get_jwks() -> dict:
    """Fetch and cache JWKS from Auth0."""
    global _jwks_cache
    if _jwks_cache is None:
        settings = get_settings()
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"https://{settings.auth0_domain}/.well-known/jwks.json"
            )
            response.raise_for_status()
            _jwks_cache = response.json()
    return _jwks_cache


class Auth0TokenVerifier(TokenVerifier):
    """Verifies Auth0 JWT tokens."""

    async def verify_token(self, token: str) -> AccessToken | None:
        settings = get_settings()

        if not settings.auth_enabled:
            # Return a dummy token for local dev
            return AccessToken(
                token=token,
                client_id="anonymous",
                scopes=["mcp:tools"],
                expires_at=None,
            )

        try:
            jwks = await get_jwks()
            unverified_header = jwt.get_unverified_header(token)

            # Find the signing key
            rsa_key = None
            for key in jwks["keys"]:
                if key["kid"] == unverified_header["kid"]:
                    rsa_key = {
                        "kty": key["kty"],
                        "kid": key["kid"],
                        "use": key["use"],
                        "n": key["n"],
                        "e": key["e"],
                    }
                    break

            if not rsa_key:
                return None

            # Verify the token
            payload = jwt.decode(
                token,
                rsa_key,
                algorithms=["RS256"],
                audience=settings.auth0_audience,
                issuer=settings.issuer_url,
            )

            # Extract scopes from token
            scopes = payload.get("scope", "").split()

            return AccessToken(
                token=token,
                client_id=payload.get("azp") or payload.get("sub", "unknown"),
                scopes=scopes,
                expires_at=payload.get("exp"),
            )

        except JWTError:
            return None
