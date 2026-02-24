"""
Credential store and {{vault:...}} token substitution.

Provides a CredentialVault that holds credentials keyed by domain,
and resolves vault reference tokens at execution time so the LLM
never sees actual credential values.
"""

import re
from urllib.parse import urlparse
from typing import Optional


class VaultKeyError(Exception):
    """Raised when a vault token cannot be resolved."""
    pass


class CredentialVault:
    """
    Credential store that resolves {{vault:field}} tokens.

    Credentials are organized by domain:
    {
        "amazon.in": {"username": "test_user", "password": "s3cure"},
        "staging.myapp.com": {"username": "admin", "password": "adm1n"}
    }
    """

    # Pattern matching {{vault:field_name}}
    VAULT_PATTERN = re.compile(r"^\{\{vault:(\w+)\}\}$")

    def __init__(self, credentials: Optional[dict] = None):
        self._credentials = credentials or {}

    @staticmethod
    def extract_domain(url: str) -> str:
        """Extract the domain from a URL."""
        parsed = urlparse(url)
        domain = parsed.hostname or parsed.path
        # Strip www. prefix for matching
        if domain.startswith("www."):
            domain = domain[4:]
        return domain

    def resolve_token(self, token: str, current_url: str) -> str:
        """
        Resolve a {{vault:field}} token to the actual credential value.

        Args:
            token: A string like "{{vault:password}}" or "{{vault:username}}"
            current_url: The current page URL, used to determine which domain's
                        credentials to look up.

        Returns:
            The actual credential value.

        Raises:
            VaultKeyError: If the token can't be resolved.
        """
        match = self.VAULT_PATTERN.match(token.strip())
        if not match:
            raise VaultKeyError(f"Invalid vault token format: {token}")

        field = match.group(1)
        domain = self.extract_domain(current_url)

        # Try exact domain match first, then partial matches
        creds = self._credentials.get(domain)
        if not creds:
            # Try matching any key that's a substring or superstring
            for key in self._credentials:
                if key in domain or domain in key:
                    creds = self._credentials[key]
                    break

        if not creds:
            raise VaultKeyError(
                f"No credentials found for domain '{domain}'. "
                f"Available domains: {list(self._credentials.keys())}"
            )

        value = creds.get(field)
        if value is None:
            raise VaultKeyError(
                f"Field '{field}' not found in credentials for domain '{domain}'. "
                f"Available fields: {list(creds.keys())}"
            )

        return value

    def is_vault_token(self, value: str) -> bool:
        """Check if a value is a vault reference token."""
        return bool(self.VAULT_PATTERN.match(value.strip())) if value else False

    def has_credentials_for(self, domain: str) -> bool:
        """Check if credentials exist for a given domain."""
        if domain in self._credentials:
            return True
        for key in self._credentials:
            if key in domain or domain in key:
                return True
        return False

    def get_available_domains(self) -> list[str]:
        """Get list of domains that have credentials (for Planner prompt)."""
        return list(self._credentials.keys())
