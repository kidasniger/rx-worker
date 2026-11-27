"""Smoke test Chromium du rendu gsapvideo : charge la fixture golden dans un
Chromium réel, injecte JS_HELPERS (ponts de rendu + primitives MD.*) comme le
fait html2mp4, seek à plusieurs instants via le vrai chemin __seek, puis échoue
si une erreur JavaScript survient ou si la capture est vide.

Utilisé par le workflow « Golden test » (hebdomadaire) et exécutable en local :
    python h2m/smoke_test.py --fixture tests/fixtures/golden_gsap.html
Le Chromium est cherché dans le PATH ou dans le cache Playwright.
"""
import argparse
import base64
import glob
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from h2m.browser import (BrowserStartupError, CDP, launch_chrome,
                         page_ws_url, start_local_http_server, stop_chrome)
from h2m.scripts_js import JS_HELPERS

CANDIDATS = ("chromium", "chromium-browser", "google-chrome", "google-chrome-stable", "chrome")
SEEKS = (0.3, 1.2, 2.0)


def trouver_chrome(explicite):
    """--chrome, puis CHROME_PATH, puis le PATH, puis le cache Playwright."""
    for candidat in (explicite, os.environ.get("CHROME_PATH")):
        if candidat and Path(candidat).is_file():
            return candidat
    for nom in CANDIDATS:
        p = shutil.which(nom)
        if p:
            return p
    motif = os.path.join(os.path.expanduser("~"), ".cache", "ms-playwright",
                         "chromium-*", "chrome-linux*", "chrome")
    for p in sorted(glob.glob(motif), reverse=True):
        if os.path.isfile(p) and os.access(p, os.X_OK):
            return p
    return None


def main():
    racine = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description="Smoke test Chromium gsapvideo")
    parser.add_argument("--fixture", default=str(racine / "tests" / "fixtures" / "golden_gsap.html"))
    parser.add_argument("--chrome", default="")
    parser.add_argument("--capture", default="golden-smoke.png")
    args = parser.parse_args()

    fixture = Path(args.fixture).resolve() if Path(args.fixture).is_absolute() else (racine / args.fixture).resolve()
    if not fixture.is_file():
        print("Fixture absente : %s" % fixture)
        return 2
    chrome = trouver_chrome(args.chrome)
    if not chrome:
        print("Aucun Chromium trouvé (PATH ou cache Playwright).")
        return 2

    tmp = Path(tempfile.mkdtemp(prefix="golden-smoke-"))
    serveur = start_local_http_server(str(fixture.parent))
    url = serveur.url_for(fixture.name)
    proc = None
    code = 1
    try:
        try:
            proc, port = launch_chrome(chrome, tmp, 540, 960)
        except BrowserStartupError as erreur:
            print("Chromium inaccessible : %s" % erreur)
            return 2
        cdp = CDP(page_ws_url(port))
        cdp.call("Page.enable")
        # Même mécanique que le rendu réel : les ponts et primitives sont posés
        # AVANT les scripts de la page.
        cdp.call("Page.addScriptToEvaluateOnNewDocument", source=JS_HELPERS)
        cdp.call("Page.navigate", url=url)
        pret = False
        for _ in range(80):
            time.sleep(0.25)
            try:
                if cdp.ev("document.readyState") == "complete":
                    pret = True
                    break
            except Exception:
                continue
        if not pret:
            print("La page ne s'est jamais chargée (20 s).")
            return 1

        etat = cdp.ev("({gsap: !!window.gsap, md: !!window.MD, "
                      "tl: (typeof tl !== 'undefined' && tl && tl.duration ? Math.round(tl.duration() * 100) / 100 : 0)})")
        print("  gsap=%s md=%s durée_tl=%ss" % (etat.get("gsap"), etat.get("md"), etat.get("tl")))
        if not etat.get("gsap") or not etat.get("md") or not etat.get("tl"):
            print("Échec : GSAP, MD ou la timeline sont indisponibles dans la page.")
            return 1

        for t in SEEKS:
            cdp.ev("window.__seek(%s)" % t)
        print("  seeks OK : %s" % (", ".join(str(t) for t in SEEKS),))

        erreurs = cdp.ev("JSON.stringify(window.__md_errors || [])")
        if erreurs != "[]":
            print("Erreurs JavaScript capturées : %s" % erreurs)
            return 1

        capture = cdp.call("Page.captureScreenshot", format="png").get("data")
        if not capture:
            print("Échec : capture d'écran vide.")
            return 1
        chemin = Path(args.capture).resolve()
        chemin.parent.mkdir(parents=True, exist_ok=True)
        chemin.write_bytes(base64.b64decode(capture))
        # Analyse pixels : l'image ne doit être ni vide ni unie.
        try:
            from PIL import Image
            import statistics
            with Image.open(chemin) as image:
                gris = list(image.convert("L").getdata())
                ecart = statistics.pstdev(gris)
                moyenne = statistics.fmean(gris)
            print("  capture %s : %dx%d, écart-type %.1f, moyenne %.1f" % (chemin.name, *Image.open(chemin).size, ecart, moyenne))
            if ecart < 4 or moyenne > 250:
                print("Échec : la capture est vide ou uniforme (écart-type %.1f)." % ecart)
                return 1
        except ImportError:
            print("  Pillow absent : analyse pixels ignorée (capture conservée).")

        print("SMOKE OK : primitives MD, seek déterministe et capture validés.")
        code = 0
        return code
    finally:
        if proc is not None:
            stop_chrome(proc)
        serveur.close()
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
