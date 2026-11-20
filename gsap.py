"""Animation IA RENDRAX : écrit les scènes gsapvideo avec GLM-4.5-Flash (Z.ai).

Par défaut, seuls des états sont journalisés. Avec DEBUG_LOGS=1 (variable de dépôt
GSAP_DEBUG, à réserver aux tests : le dépôt est public), tout le déroulé est affiché.
Variables : JOB_ID, ZAI_API_KEY, ZAI_MODEL (défaut glm-4.5-flash), ZAI_THINKING.
"""
import json
import os
import re
import socket
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

BASE = "https://rendrax.vercel.app/api/generate"
AUDIENCE = "https://rendrax.vercel.app/kidas-render"
ZAI_URL = "https://api.z.ai/api/paas/v4/chat/completions"
MODEL = os.environ.get("ZAI_MODEL", "glm-4.5-flash")
THINKING = os.environ.get("ZAI_THINKING", "disabled")
KEY = os.environ.get("ZAI_API_KEY", "")
JOB_ID = os.environ.get("JOB_ID", "")
RUN_ID = os.environ.get("GITHUB_RUN_ID", "")
DEBUG = os.environ.get("DEBUG_LOGS", "") == "1"
ESSAIS_SCENE = 3
ESSAIS_API = 5
PAUSE_SCENES = 3

if not re.fullmatch(r"[A-Za-z0-9_-]{6,64}", JOB_ID) or not RUN_ID.isdigit():
    sys.exit("Paramètres invalides.")
if not KEY:
    sys.exit("Clé du service d'IA absente.")


def log(message):
    print(message, flush=True)


class Lignes:
    """Affiche un texte ligne par ligne, avec un préfixe (jamais de commande ::)."""

    def __init__(self, prefixe):
        self.prefixe = prefixe
        self.tampon = ""

    def ajouter(self, texte):
        self.tampon += texte
        while "\n" in self.tampon:
            ligne, self.tampon = self.tampon.split("\n", 1)
            print(self.prefixe + ligne, flush=True)

    def fin(self):
        if self.tampon:
            print(self.prefixe + self.tampon, flush=True)
            self.tampon = ""


def bloc(titre, texte, prefixe):
    print("::group::" + titre, flush=True)
    lignes = Lignes(prefixe)
    lignes.ajouter(texte + "\n")
    print("::endgroup::", flush=True)


def http(method, url, headers=None, data=None, timeout=60):
    corps = json.dumps(data).encode("utf-8") if data is not None else None
    entetes = dict(headers or {})
    if corps is not None:
        entetes["Content-Type"] = "application/json"
    requete = urllib.request.Request(url, data=corps, headers=entetes, method=method)
    try:
        with urllib.request.urlopen(requete, timeout=timeout) as reponse:
            return reponse.status, reponse.read()
    except urllib.error.HTTPError as erreur:
        return erreur.code, erreur.read()


def oidc():
    url = os.environ["ACTIONS_ID_TOKEN_REQUEST_URL"] + "&audience=" + urllib.parse.quote(AUDIENCE, safe="")
    statut, brut = http("GET", url, {"Authorization": "Bearer " + os.environ["ACTIONS_ID_TOKEN_REQUEST_TOKEN"]})
    if statut != 200:
        raise RuntimeError("jeton OIDC indisponible (HTTP %s)" % statut)
    jeton = json.loads(brut)["value"]
    print("::add-mask::" + jeton, flush=True)
    return jeton


def vercel(action, charge=None):
    entetes = {"Authorization": "Bearer " + oidc()}
    if charge is None:
        url = "%s?action=%s&id=%s&run_id=%s" % (BASE, action, JOB_ID, RUN_ID)
        statut, brut = http("GET", url, entetes)
    else:
        charge = dict(charge, id=JOB_ID, run_id=RUN_ID)
        statut, brut = http("POST", "%s?action=%s" % (BASE, action), entetes, charge)
    if statut != 200:
        raise RuntimeError("%s : HTTP %s" % (action, statut))
    return json.loads(brut)


def lire_flux(reponse, debut):
    contenu = []
    premier = None
    mode = None
    usage = None
    pensee_log = Lignes("    ~ ")
    code_log = Lignes("    | ")
    if DEBUG:
        print("::group::Réponse de l'IA en direct", flush=True)
    try:
        for brut in reponse:
            ligne = brut.decode("utf-8", "replace").strip()
            if not ligne.startswith("data:"):
                continue
            donnees = ligne[5:].strip()
            if donnees == "[DONE]":
                break
            try:
                morceau = json.loads(donnees)
            except ValueError:
                continue
            if morceau.get("usage"):
                usage = morceau["usage"]
            choix = (morceau.get("choices") or [{}])[0]
            delta = choix.get("delta") or {}
            pensee = delta.get("reasoning_content") or ""
            texte = delta.get("content") or ""
            if (pensee or texte) and premier is None:
                premier = time.time() - debut
                log("  premier jeton après %.1f s" % premier)
            if pensee and DEBUG:
                if mode != "p":
                    print("  --- réflexion de l'IA ---", flush=True)
                    mode = "p"
                pensee_log.ajouter(pensee)
            if texte:
                contenu.append(texte)
                if DEBUG:
                    if mode != "c":
                        pensee_log.fin()
                        print("  --- code écrit par l'IA ---", flush=True)
                        mode = "c"
                    code_log.ajouter(texte)
    finally:
        if DEBUG:
            pensee_log.fin()
            code_log.fin()
            print("::endgroup::", flush=True)
    if usage:
        log("  jetons : envoyés %s, reçus %s" % (usage.get("prompt_tokens"), usage.get("completion_tokens")))
    return "".join(contenu)


def ecrire(systeme, utilisateur):
    corps = {
        "model": MODEL,
        "messages": [
            {"role": "system", "content": systeme},
            {"role": "user", "content": utilisateur},
        ],
        "temperature": 0.4,
        "max_tokens": 8000,
        "stream": True,
    }
    if THINKING in ("enabled", "disabled"):
        corps["thinking"] = {"type": THINKING}
    entetes = {
        "Authorization": "Bearer " + KEY,
        "Content-Type": "application/json",
        "Accept": "text/event-stream",
    }
    for essai in range(1, ESSAIS_API + 1):
        debut = time.time()
        requete = urllib.request.Request(
            ZAI_URL, data=json.dumps(corps).encode("utf-8"), headers=entetes, method="POST")
        try:
            with urllib.request.urlopen(requete, timeout=90) as reponse:
                texte = lire_flux(reponse, debut)
            log("  réponse reçue : %d caractères en %.1f s" % (len(texte), time.time() - debut))
            if not texte.strip():
                raise RuntimeError("réponse vide")
            return texte
        except urllib.error.HTTPError as erreur:
            statut = erreur.code
            if DEBUG:
                log("  détail : " + erreur.read()[:300].decode("utf-8", "replace"))
            if statut == 400 and "thinking" in corps:
                del corps["thinking"]
                log("  réglage de réflexion refusé, nouvel essai sans")
                continue
            if statut in (429, 500, 502, 503, 504):
                attente = 10 * essai
                log("  service d'IA occupé (HTTP %s), attente %s s" % (statut, attente))
                time.sleep(attente)
                continue
            raise RuntimeError("service d'IA : HTTP %s" % statut)
        except (socket.timeout, TimeoutError, urllib.error.URLError, ConnectionError, OSError) as erreur:
            attente = 5 * essai
            log("  coupure ou délai (%s), nouvel essai dans %s s" % (type(erreur).__name__, attente))
            time.sleep(attente)
    raise RuntimeError("service d'IA indisponible après %s essais" % ESSAIS_API)


def main():
    log("Récupération des scènes...")
    scenes = vercel("gsapw-source")["scenes"]
    log("%d scène(s) à écrire (modèle %s, réflexion %s)." % (len(scenes), MODEL, THINKING))
    log("Mode détaillé : " + ("oui" if DEBUG else "non"))
    for n, scene in enumerate(scenes, 1):
        index = scene["index"]
        utilisateur = scene["user"]
        reussi = False
        for essai in range(1, ESSAIS_SCENE + 1):
            log("Scène %d/%d : tentative %d" % (n, len(scenes), essai))
            if DEBUG:
                bloc("Consigne système (scène %d)" % n, scene["system"], "    # ")
                bloc("Consigne de la scène %d" % n, utilisateur, "    > ")
            try:
                contenu = ecrire(scene["system"], utilisateur)
            except Exception as erreur:  # noqa: BLE001
                log("  erreur : %s" % erreur)
                time.sleep(5)
                continue
            try:
                resultat = vercel("gsapw-check", {"index": index, "content": contenu})
            except Exception as erreur:  # noqa: BLE001
                log("  contrôle indisponible : %s" % erreur)
                time.sleep(5)
                continue
            if resultat.get("ok"):
                log("  contrôle : accepté")
                reussi = True
                break
            log("  contrôle : refusé")
            fix = str(resultat.get("fix", ""))
            if DEBUG:
                bloc("Problèmes signalés par le contrôle", fix, "    ! ")
            utilisateur = scene["user"] + "\n\n" + fix
        if not reussi:
            try:
                vercel("gsapw-fail", {"index": index})
            except Exception as erreur:  # noqa: BLE001
                log("  échec non signalé : %s" % erreur)
            raise RuntimeError("scène %d non écrite" % (index + 1))
        log("Scène %d/%d écrite." % (n, len(scenes)))
        time.sleep(PAUSE_SCENES)
    log("Toutes les scènes sont écrites.")


if __name__ == "__main__":
    probleme = None
    try:
        main()
    except Exception as erreur:  # noqa: BLE001
        probleme = erreur
    try:
        vercel("gsapw-cleanup", {})
    except Exception as erreur:  # noqa: BLE001
        log("Nettoyage non effectué : %s" % erreur)
    if probleme:
        sys.exit("Échec : %s" % probleme)
