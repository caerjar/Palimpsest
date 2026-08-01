"""Injection payloads, in one place so a new sink gets coverage for free.

Every string here is pushed through every authored-text field the app has, and the
generated dossier is then asserted clean. Adding a payload here tightens every
escaping test at once; adding a sink to test_escaping.py does the same in reverse.
"""

# Break out of a <script> block. json.dumps does NOT escape "/", so a value
# containing </script> ends the tag early unless the embed guards it.
SCRIPT_BREAKOUT = [
    "</script><img src=x onerror=alert(1)>",
    "</script><script>alert(1)</script>",
    "</SCRIPT ><svg onload=alert(1)>",          # tag matching is case-insensitive
]

# Escape an HTML attribute or a text node.
MARKUP = [
    '"><script>alert(1)</script>',
    "'><img src=x onerror=alert(1)>",
    "<img src=x onerror=alert(1)>",
]

# Close a style attribute / <style> block (colors land in style="…").
STYLE = [
    "#000; background:url(javascript:alert(1))",
    "red</style><script>alert(1)</script>",
]

# Reach XeLaTeX. pandoc runs with raw_tex on, so a surviving control word is
# executed rather than printed. \input is an arbitrary-file-read primitive under
# TeX Live's default openin_any=a.
#
# The doubled form is the important one: an escaper that rewrites backslashes
# one at a time lets "\\input" re-form into a live "\input".
LATEX = [
    r"\input{/etc/hostname}",
    "\\\\input{/etc/hostname}",                 # the pre-doubled bypass
    "\\\\\\input{/etc/hostname}",
    r"\immediate\write18{id}",
]

# Prose that must survive intact — an escaper that mangles these is too greedy.
BENIGN = [
    r'printf("...\n")',
    r"100\% sure",
    r"\*not italic\*",
    "a — b",                                    # non-ASCII must round-trip
    "quote \" and ' apostrophe",
]

ALL_HOSTILE = SCRIPT_BREAKOUT + MARKUP + STYLE + LATEX


DANGEROUS = r"\\(input|include|write|immediate|openin|read|catcode|def|let)\b"


def latex_is_live(rendered: str) -> bool:
    """True if a LaTeX control word survived as an *executable* command.

    `\\textbackslash{}` is the safe rendering of a literal backslash, so strip
    every one of those first; whatever backslashes remain are real control
    sequences. Doing it by removal rather than by lookbehind matters: a naive
    `(?<!textbackslash\\{\\})` would suppress `\\textbackslash{}\\input{...}`,
    which is a printed backslash followed by a LIVE control word — exactly the
    case this has to catch.
    """
    import re
    stripped = re.sub(r"\\textbackslash\s*(\{\})?", "", rendered)
    return bool(re.search(DANGEROUS, stripped))
