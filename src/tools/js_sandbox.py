"""
JavaScript execution sandbox with allowlist/blocklist validation.

The evaluate_javascript tool allows the LLM to run JS in the browser.
This module ensures only read-only operations are permitted.
"""

import re

from playwright.async_api import Page


# Allowed JS patterns (read-only operations)
JS_ALLOWLIST = [
    r'JSON\.stringify\(localStorage\)',
    r'JSON\.stringify\(sessionStorage\)',
    r'document\.cookie',
    r'document\.title',
    r'document\.querySelector\(.+\)\.(textContent|innerText|value|checked|href|src)',
    r'window\.location\.(href|pathname|search|hash)',
    r'document\.querySelectorAll\(.+\)\.length',
    r'document\.body\.innerText',
    r'getComputedStyle\(.+\)\.\w+',
    r'window\.\w+',
    r'performance\.(now|getEntriesByType)\(',
    r'document\.readyState',
    r'navigator\.\w+',
]

# Blocked patterns (write/network operations)
JS_BLOCKLIST = [
    r'fetch\s*\(',
    r'XMLHttpRequest',
    r'\.innerHTML\s*=',
    r'\.outerHTML\s*=',
    r'document\.write',
    r'document\.writeln',
    r'eval\s*\(',
    r'Function\s*\(',
    r'setTimeout\s*\(',
    r'setInterval\s*\(',
    r'\.remove\(\)',
    r'\.removeChild\(',
    r'\.replaceWith\(',
    r'\.setAttribute\(',
    r'import\s*\(',
    r'require\s*\(',
]

_ALLOWLIST_COMPILED = [re.compile(p) for p in JS_ALLOWLIST]
_BLOCKLIST_COMPILED = [re.compile(p) for p in JS_BLOCKLIST]


def validate_javascript(script: str) -> tuple[bool, str]:
    """
    Validate a JS script against the allowlist/blocklist.

    Returns (is_allowed, reason).

    Strategy: blocklist-first (reject dangerous patterns),
    then allowlist (must match at least one safe pattern),
    fail-closed default (unknown = blocked).
    """
    # Check blocklist first
    for pattern in _BLOCKLIST_COMPILED:
        if pattern.search(script):
            return False, f"Blocked pattern detected: {pattern.pattern}"

    # Check if script matches at least one allowlist pattern
    for pattern in _ALLOWLIST_COMPILED:
        if pattern.search(script):
            return True, "Matches allowlist"

    # Unknown pattern — block by default (fail-closed)
    return False, (
        "Script does not match any allowed pattern. "
        "Only read-only operations are permitted."
    )


async def evaluate_javascript_safe(page: Page, script: str) -> str:
    """
    Validate and execute a JavaScript snippet in the browser.

    Returns the evaluation result as a string, or an error/block message.
    """
    allowed, reason = validate_javascript(script)
    if not allowed:
        return f"BLOCKED: {reason}"

    try:
        result = await page.evaluate(script)
        return str(result) if result is not None else "undefined"
    except Exception as e:
        return f"JS execution error: {str(e)}"
