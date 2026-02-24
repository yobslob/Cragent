"""Tests for the credential vault."""

import pytest
from src.security.vault import CredentialVault, VaultKeyError


class TestCredentialVault:
    def test_resolve_password_token(self):
        vault = CredentialVault({
            "example.com": {"username": "admin", "password": "s3cret"}
        })
        result = vault.resolve_token("{{vault:password}}", "https://example.com/login")
        assert result == "s3cret"

    def test_resolve_username_token(self):
        vault = CredentialVault({
            "example.com": {"username": "admin", "password": "s3cret"}
        })
        result = vault.resolve_token("{{vault:username}}", "https://example.com/login")
        assert result == "admin"

    def test_domain_extraction_strips_www(self):
        vault = CredentialVault({
            "example.com": {"username": "admin", "password": "pass"}
        })
        result = vault.resolve_token("{{vault:username}}", "https://www.example.com/page")
        assert result == "admin"

    def test_partial_domain_match(self):
        vault = CredentialVault({
            "myapp.com": {"username": "admin", "password": "pass"}
        })
        result = vault.resolve_token("{{vault:username}}", "https://staging.myapp.com/login")
        assert result == "admin"

    def test_missing_domain_raises(self):
        vault = CredentialVault({"other.com": {"username": "x", "password": "y"}})
        with pytest.raises(VaultKeyError, match="No credentials found"):
            vault.resolve_token("{{vault:password}}", "https://example.com/login")

    def test_missing_field_raises(self):
        vault = CredentialVault({
            "example.com": {"username": "admin"}
        })
        with pytest.raises(VaultKeyError, match="Field 'password' not found"):
            vault.resolve_token("{{vault:password}}", "https://example.com/login")

    def test_invalid_token_format(self):
        vault = CredentialVault({"example.com": {"password": "pass"}})
        with pytest.raises(VaultKeyError, match="Invalid vault token"):
            vault.resolve_token("not-a-vault-token", "https://example.com")

    def test_is_vault_token(self):
        vault = CredentialVault()
        assert vault.is_vault_token("{{vault:password}}") is True
        assert vault.is_vault_token("{{vault:username}}") is True
        assert vault.is_vault_token("regular text") is False
        assert vault.is_vault_token("") is False
        assert vault.is_vault_token(None) is False

    def test_has_credentials_for(self):
        vault = CredentialVault({"example.com": {"username": "admin", "password": "pass"}})
        assert vault.has_credentials_for("example.com") is True
        assert vault.has_credentials_for("other.com") is False

    def test_get_available_domains(self):
        vault = CredentialVault({
            "example.com": {"username": "a", "password": "b"},
            "myapp.com": {"username": "c", "password": "d"},
        })
        domains = vault.get_available_domains()
        assert "example.com" in domains
        assert "myapp.com" in domains
        assert len(domains) == 2

    def test_empty_vault(self):
        vault = CredentialVault()
        assert vault.get_available_domains() == []
        assert vault.has_credentials_for("anything") is False
