"""Contrat gsapvideo de la fixture golden : les 8 signatures attendues par le
serveur RENDRAX (lib/kidas-gsapvideo.js, CONTRACT_TESTS), vérifiées côté worker.
Usage : python tests/check_contrat.py tests/fixtures/golden_gsap.html
"""
import re
import sys

CONTRAT = [
    ("piste voix base64", r"<audio\b[^>]*\bsrc=[\"']data:audio/[a-z0-9.+-]+;base64,"),
    ("constante de durée", r"\b(?:const\s+T\s*=\s*\[\s*\d|const\s+D\s*=\s*\d)"),
    ("sous-titres SUB", r"\bSUB\s*="),
    ("timeline GSAP en pause", r"\btl\s*=\s*gsap\.timeline\(\s*\{\s*paused\s*:\s*true\s*\}\s*\)"),
    ("seek déterministe tl.time", r"\btl\.time\([^;]*?,\s*false\s*\)"),
    ("lecture liée à l'audio",
     r"\bstarted\s*\?\s*a\.currentTime|\bif\s*\(\s*started\s*\)\s*\{[\s\S]{0,1200}?\ba\.currentTime\b"),
    ("boucle rAF nommée lp", r"requestAnimationFrame\s*\(\s*lp\s*\)"),
    ("scène #st dimensionnée", r"[.#]st\s*\{[^}]*?width:\s*\d+px;\s*height:\s*\d+px"),
]


def main(argv):
    if len(argv) != 2:
        print("Usage : python tests/check_contrat.py <fichier.html>")
        return 2
    with open(argv[1], encoding="utf-8") as source:
        html = source.read()
    absents = []
    for nom, motif in CONTRAT:
        if re.search(motif, html, re.IGNORECASE):
            print("  OK   %s" % nom)
        else:
            print("  ABSENT  %s" % nom)
            absents.append(nom)
    if absents:
        print("Contrat non respecté : %s" % ", ".join(absents))
        return 1
    print("Contrat gsapvideo respecté (%d signatures)." % len(CONTRAT))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
