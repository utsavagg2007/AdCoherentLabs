"""Contrast audit over the token file itself.

Resolves the primitive ramp, then each theme's semantic layer (light, dark),
composites every alpha fill over its backing surface, and checks the text
pairings the components actually use against WCAG AA.

Reads globals.css directly, so it stays true as the palette is tuned and
does not depend on a browser being able to paint.
"""

import io
import re
import sys

CSS = "src/app/globals.css"


def srgb(c):
    c = c / 255
    return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4


def lum(rgb):
    r, g, b = (srgb(v) for v in rgb[:3])
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def ratio(fg, bg):
    a, b = lum(fg), lum(bg)
    hi, lo = max(a, b), min(a, b)
    return (hi + 0.05) / (lo + 0.05)


def over(fg, bg):
    """Composite an rgba colour onto an opaque backdrop."""
    if len(fg) < 4:
        return fg[:3]
    a = fg[3]
    return tuple(fg[i] * a + bg[i] * (1 - a) for i in range(3))


HEX = re.compile(r"^#([0-9a-fA-F]{3}|[0-9a-fA-F]{6})$")
RGBFN = re.compile(r"^rgb\(\s*([\d.]+)\s+([\d.]+)\s+([\d.]+)\s*(?:/\s*([\d.]+)\s*)?\)$")
VAR = re.compile(r"^var\(\s*(--[\w-]+)\s*\)$")


def parse_color(value, table, depth=0):
    v = value.strip().rstrip(";").strip()
    if depth > 8:
        return None
    m = VAR.match(v)
    if m:
        return parse_color(table.get(m.group(1), ""), table, depth + 1)
    m = HEX.match(v)
    if m:
        h = m.group(1)
        if len(h) == 3:
            h = "".join(ch * 2 for ch in h)
        return tuple(int(h[i : i + 2], 16) for i in (0, 2, 4))
    m = RGBFN.match(v)
    if m:
        rgb = tuple(float(m.group(i)) for i in (1, 2, 3))
        return rgb + (float(m.group(4)),) if m.group(4) else rgb
    return None


def decls(block):
    out = {}
    for name, val in re.findall(r"(--[\w-]+)\s*:\s*([^;]+);", block):
        out[name] = val.strip()
    return out


def block_after(src, selector):
    """Body of the first top-level rule whose selector text matches."""
    i = src.find(selector)
    if i < 0:
        raise SystemExit(f"selector not found: {selector}")
    start = src.index("{", i) + 1
    depth, j = 1, start
    while depth:
        if src[j] == "{":
            depth += 1
        elif src[j] == "}":
            depth -= 1
        j += 1
    return src[start : j - 1]


def main():
    src = io.open(CSS, encoding="utf-8").read()
    # strip comments so a commented-out token never wins
    src = re.sub(r"/\*.*?\*/", "", src, flags=re.S)

    primitives = decls(block_after(src, ":root {"))
    light = dict(primitives)
    light.update(decls(block_after(src, ":root {")))
    # the second bare :root block holds the light semantics
    second = src.index(":root {", src.index(":root {") + 1)
    light.update(decls(block_after(src[second:], ":root {")))

    dark = dict(light)
    dark.update(decls(block_after(src, ':root[data-theme="dark"]')))

    # text tier -> the surfaces it is allowed to appear on
    SURFACES = ["--surface-canvas", "--surface-sunken", "--surface", "--surface-raised"]
    TEXT = ["--text-strong", "--text-body", "--text-muted", "--text-subtle", "--text-faint"]

    # tinted signal fills: (text token, fill token, backing surface)
    SIGNALS = [
        ("--pass-fg", "--pass-soft"),
        ("--warn-fg", "--warn-soft"),
        ("--fail-fg", "--fail-soft"),
        ("--live-fg", "--live-soft"),
        ("--brand-text", "--brand-soft"),
        ("--accent-text", "--accent-soft"),
    ]

    fails = []
    checked = 0

    for theme_name, table in (("light", light), ("dark", dark)):
        for t in TEXT:
            fg = parse_color(table.get(t, ""), table)
            if not fg:
                fails.append((theme_name, t, "unresolved", 0))
                continue
            for s in SURFACES:
                bg = parse_color(table.get(s, ""), table)
                if not bg:
                    continue
                checked += 1
                r = ratio(fg, bg)
                if r < 4.5:
                    fails.append((theme_name, f"{t} on {s}", "AA text", round(r, 2)))

        for fgtok, filltok in SIGNALS:
            fg = parse_color(table.get(fgtok, ""), table)
            fill = parse_color(table.get(filltok, ""), table)
            if not fg or not fill:
                fails.append((theme_name, f"{fgtok}/{filltok}", "unresolved", 0))
                continue
            for s in ("--surface", "--surface-canvas"):
                base = parse_color(table.get(s, ""), table)
                bg = over(fill, base)
                checked += 1
                r = ratio(over(fg, bg), bg)
                if r < 4.5:
                    fails.append((theme_name, f"{fgtok} on {filltok}/{s}", "AA text", round(r, 2)))

        # solid brand/destructive fills: the label sits directly on them,
        # so every gradient stop and every hover state has to clear AA
        for stop, ontok in (
            ("--cta-1", "--brand-on"),
            ("--cta-2", "--brand-on"),
            ("--cta-3", "--brand-on"),
            ("--brand", "--brand-on"),
            ("--danger", "--danger-on"),
            ("--danger-hover", "--danger-on"),
        ):
            c = parse_color(table.get(stop, ""), table)
            on = parse_color(table.get(ontok, ""), table)
            if c and on:
                checked += 1
                r = ratio(on, c)
                if r < 4.5:
                    fails.append((theme_name, f"{ontok} on {stop}", "AA text", round(r, 2)))

    print(f"checked {checked} pairs across light + dark")
    if not fails:
        print("PASS - every pairing clears WCAG AA (4.5:1)")
        return 0
    print(f"\n{len(fails)} FAILING pairs:")
    for theme, pair, kind, r in sorted(fails, key=lambda x: x[3]):
        print(f"  [{theme:5}] {pair:52} {kind:10} {r}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
