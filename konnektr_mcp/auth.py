"""
Authentication handlers for Konnektr MCP.

Extends OIDCProxy to support both client credentials (raw Auth0 tokens) and
interactive PKCE flows, while maintaining all OIDCProxy functionality.
"""

import logging
from typing import Optional

from fastmcp.server.auth import OIDCProxy, JWTVerifier, AccessToken

logger = logging.getLogger(__name__)


class DualAuthOIDCProxy(OIDCProxy):
    """
    Extended OIDCProxy that supports both:
    1. Client credentials: Raw Auth0 tokens validated via JWTVerifier
    2. Interactive PKCE: FastMCP JWTs via parent OIDCProxy's verify_token

    Extends OIDCProxy to preserve all its functionality (routes, middleware, etc.)
    while adding client credentials support.
    """

    def __init__(self, jwt_verifier: JWTVerifier, **oidc_proxy_kwargs):
        """
        Initialize the dual auth OIDC proxy.

        Args:
            jwt_verifier: JWTVerifier instance for client credentials flow
            **oidc_proxy_kwargs: All arguments to pass to OIDCProxy.__init__
        """
        super().__init__(**oidc_proxy_kwargs)
        self.jwt_verifier = jwt_verifier

    async def verify_token(self, token: str) -> Optional[AccessToken]:
        """
        Verify a token using either JWTVerifier or OIDCProxy's verify_token.

        Tries JWTVerifier first (client credentials Auth0 tokens),
        then falls back to OIDCProxy's verify_token (FastMCP JWTs from interactive flow).

        Args:
            token: The token to validate

        Returns:
            AccessToken if validation succeeds, None otherwise
        """
        # Try JWTVerifier first (validates raw Auth0 tokens)
        try:
            logger.debug("Attempting JWTVerifier validation for client credentials...")
            access_token = await self.jwt_verifier.verify_token(token)
            if access_token:
                logger.info("Token validated via JWTVerifier (client credentials flow)")
                return access_token
        except Exception as e:
            logger.debug(f"JWTVerifier validation failed: {e}")

        # Fall back to parent OIDCProxy's verify_token (interactive PKCE flow)
        try:
            logger.debug("Attempting OIDC proxy validation for interactive flow...")
            access_token = await super().verify_token(token)
            if access_token:
                logger.info("Token validated via OIDCProxy (interactive PKCE flow)")
                return access_token
        except Exception as e:
            logger.debug(f"OIDC proxy validation failed: {e}")

        logger.warning("Token validation failed for both JWTVerifier and OIDCProxy")
        return None
