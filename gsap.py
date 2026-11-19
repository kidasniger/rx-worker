"""Animation IA RENDRAX : écrit les scènes gsapvideo avec GLM-4.5-Flash (Z.ai).

Dépôt public : seuls des états sont journalisés, jamais les prompts ni le code.
Variables : JOB_ID, ZAI_API_KEY, ZAI_MODEL (défaut glm-4.5-flash), ZAI_THINKING.
"""
import json
import os
import re
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
ESSAIS_SCENE = 3
ESSAIS_API = 5
PAUSE_SCENES = 3

if not re.fullmatch(r"[A-Za-z0-9_-]{6,64}", JOB_ID) or not RUN_ID.isdigit():
    sys.exit("Paramètres invalides.")
if not KEY:
    sys.exit("Clé du service d'IA absente.")


def log(message):
    print(message, flush=True)


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


def ecrire(systeme, utilisateur):
    corps = {
        "model": MODEL,
        "messages": [
            {"role": "system", "content": systeme},
            {"role": "user", "content": utilisateur},
        ],
        "temperature": 0.4,
        "max_tokens": 8000,
    }
    if THINKING in ("enabled", "disabled"):
        corps["thinking"] = {"type": THINKING}
    entetes = {"Authorization": "Bearer " + KEY}
    for essai in range(1, ESSAIS_API + 1):
        statut, brut = http("POST", ZAI_URL, entetes, corps, timeout=150)
        if statut == 200:
            try:
                return json.loads(brut)["choices"][0]["message"]["content"] or ""
            except Exception:
                raise RuntimeError("réponse du service d'IA illisible")
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
    raise RuntimeError("service d'IA indisponible après %s essais" % ESSAIS_API)


def main():
    log("Récupération des scènes...")
    scenes = vercel("gsapw-source")["scenes"]
    log("%d scène(s) à écrire (modèle %s)." % (len(scenes), MODEL))
    for n, scene in enumerate(scenes, 1):
        index = scene["index"]
        utilisateur = scene["user"]
        reussi = False
        for essai in range(1, ESSAIS_SCENE + 1):
            log("Scène %d/%d : tentative %d" % (n, len(scenes), essai))
            try:
                contenu = ecrire(scene["system"], utilisateur)
                resultat = vercel("gsapw-check", {"index": index, "content": contenu})
            except Exception as erreur:  # noqa: BLE001
                log("  erreur : %s" % erreur)
                break
            if resultat.get("ok"):
                reussi = True
                break
            log("  refusée par le contrôle")
            utilisateur = scene["user"] + "\n\n" + str(resultat.get("fix", ""))
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
