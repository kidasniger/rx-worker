"""Animation IA RENDRAX : écrit les scènes gsapvideo avec GLM (Z.ai).

Par défaut, seuls des états sont journalisés. Avec DEBUG_LOGS=1 (variable de dépôt
GSAP_DEBUG, à réserver aux tests : le dépôt est public), tout le déroulé est affiché.
Variables : JOB_ID, ZAI_API_KEY, ZAI_MODEL (défaut glm-4.5-flash), ZAI_MODEL_RETRY
(modèle plus fort pour les tentatives 2+, défaut : ZAI_MODEL), ZAI_THINKING.

Fiabilité :
  - une réponse tronquée (finish_reason=length) est détectée et relancée avec plus
    de jetons au lieu de produire un JSON illisible ;
  - le JSON est vérifié localement AVANT l'appel serveur (aller-retour évité) ;
  - le bloc refusé est renvoyé dans la consigne de correction : le modèle corrige
    son propre code au lieu de repartir de zéro ;
  - chaque changement d'état est relayé à l'écran de suivi (gsapw-progress) et un
    bilan JSON est publié à la fin du run (gsapw-metrics).
"""
import json
import os
import re
import socket
import sys
import time
from collections import Counter
import urllib.error
import urllib.parse
import urllib.request

BASE = "https://rendrax.vercel.app/api/generate"
AUDIENCE = "https://rendrax.vercel.app/kidas-render"
ZAI_URL = "https://api.z.ai/api/paas/v4/chat/completions"
MODEL = os.environ.get("ZAI_MODEL", "glm-4.5-flash")
MODEL_RETRY = (os.environ.get("ZAI_MODEL_RETRY", "") or "").strip() or MODEL
THINKING = os.environ.get("ZAI_THINKING", "disabled")
KEY = os.environ.get("ZAI_API_KEY", "")
JOB_ID = os.environ.get("JOB_ID", "")
RUN_ID = os.environ.get("GITHUB_RUN_ID", "")
DEBUG = os.environ.get("DEBUG_LOGS", "") == "1"
ESSAIS_SCENE = 3
ESSAIS_API = 5
PAUSE_SCENES = 3
MAX_TOKENS = 1500
MAX_TOKENS_TRONQUE = 2600

if not re.fullmatch(r"[A-Za-z0-9_-]{6,64}", JOB_ID) or not RUN_ID.isdigit():
    sys.exit("Paramètres invalides.")
if not KEY:
    sys.exit("Clé du service d'IA absente.")

# Bilan du run, publié via gsapw-metrics à la fin (journalisation côté serveur).
DEBUT = time.time()
METRICS = {
    "total_prevu": 0,
    "scenes": 0,
    "premier_essai": 0,
    "essais_total": 0,
    "tronques": 0,
    "jetons_envoyes": 0,
    "jetons_recus": 0,
    "modeles": {},
    "refus": [],
    "duree_s": 0.0,
}


def log(message):
    print(message, flush=True)


class Boucle(RuntimeError):
    pass


class Tronque(RuntimeError):
    """Réponse coupée par la limite de jetons (finish_reason=length)."""


class Garde:
    """Coupe la réponse si le modèle boucle (même ligne répétée) ou s'éternise."""

    def __init__(self):
        self.reste = ""
        self.vues = Counter()
        self.total = 0

    def verifier(self, texte, debut):
        self.total += len(texte)
        if time.time() - debut > 90:
            raise Boucle("réponse trop longue (90 s)")
        if self.total > 5000:
            raise Boucle("réponse trop volumineuse")
        self.reste += texte
        while "\n" in self.reste:
            ligne, self.reste = self.reste.split("\n", 1)
            cle = re.sub(r"[0-9.]+", "#", ligne.strip())
            if len(cle) >= 40:
                self.vues[cle] += 1
                if self.vues[cle] >= 5:
                    raise Boucle("répétition détectée")


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


def signaler(phase, scene_n=0, scene_total=0, essai=0, label=""):
    """Relais de progression vers l'écran de suivi (jamais bloquant).

    L'action gsapw-progress est best effort : une indisponibilité temporaire
    de Vercel n'interrompt jamais l'écriture des scènes.
    """
    try:
        vercel("gsapw-progress", {
            "current": int(scene_n),
            "total": int(scene_total),
            "essai": int(essai),
            "phase": str(phase)[:24],
            "label": str(label)[:80],
        })
    except Exception as erreur:  # noqa: BLE001
        log("  progression non transmise (%s) : %s" % (phase, type(erreur).__name__))


def comptabiliser(usage):
    """Additionne les jetons du run pour le bilan gsapw-metrics."""
    if not isinstance(usage, dict):
        return
    try:
        METRICS["jetons_envoyes"] += int(usage.get("prompt_tokens") or 0)
        METRICS["jetons_recus"] += int(usage.get("completion_tokens") or 0)
    except (TypeError, ValueError):
        pass


def noter_refus(motif):
    if len(METRICS["refus"]) < 24:
        METRICS["refus"].append(str(motif)[:160])


def lire_flux(reponse, debut):
    contenu = []
    premier = None
    fin_flot = None
    mode = None
    usage = None
    garde = Garde()
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
            if choix.get("finish_reason"):
                fin_flot = choix["finish_reason"]
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
                garde.verifier(texte, debut)
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
    return "".join(contenu), fin_flot, usage


def ecrire(systeme, utilisateur, model=MODEL, max_tokens=MAX_TOKENS):
    """Une réponse du modèle : relances réseau, troncature et boucle gérées ici.

    Renvoie (texte, finish_reason, usage). Une réponse tronquée relance l'appel
    avec un plafond de jetons relevé (une fois) au lieu de produire un JSON
    coupé que le contrôle servirait à rejeter.
    """
    corps = {
        "model": model,
        "messages": [
            {"role": "system", "content": systeme},
            {"role": "user", "content": utilisateur},
        ],
        "temperature": 0.4,
        "max_tokens": max_tokens,
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
        corps["temperature"] = 0.4 if essai == 1 else 0.8
        requete = urllib.request.Request(
            ZAI_URL, data=json.dumps(corps).encode("utf-8"), headers=entetes, method="POST")
        try:
            with urllib.request.urlopen(requete, timeout=90) as reponse:
                texte, fin_flot, usage = lire_flux(reponse, debut)
            log("  réponse reçue : %d caractères en %.1f s" % (len(texte), time.time() - debut))
            if not texte.strip():
                raise RuntimeError("réponse vide")
            if fin_flot == "length":
                METRICS["tronques"] += 1
                corps["max_tokens"] = max(int(corps.get("max_tokens") or 0), MAX_TOKENS_TRONQUE)
                log("  réponse tronquée (finish_reason=length), relance avec max_tokens=%s" % corps["max_tokens"])
                raise Tronque()
            return texte, fin_flot, usage
        except Tronque:
            continue
        except Boucle as erreur:
            log("  boucle détectée (%s), nouvel essai avec plus de variété" % erreur)
            continue
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


def controle_local(texte):
    """Contrôle gratuit avant l'appel serveur : l'objet JSON doit exister et tenir debout.

    Renvoie None si le JSON est lisible, sinon le motif du refus (évite un
    aller-retour gsapw-check pour un problème détectable en local).
    """
    brut = str(texte or "")
    debut, fin = brut.find("{"), brut.rfind("}")
    if debut < 0 or fin <= debut:
        return "aucun objet JSON trouvé (réponse vide, tronquée ou hors sujet)"
    try:
        json.loads(brut[debut:fin + 1])
    except ValueError as erreur:
        return "JSON invalide : %s" % erreur
    return None


def publier_metriques(total_scenes):
    """Bilan du run côté serveur (taux d'acceptation au 1er essai, jetons, refus)."""
    if not METRICS["duree_s"]:
        METRICS["duree_s"] = round(time.time() - DEBUT, 1)
    try:
        vercel("gsapw-metrics", {
            "total": int(total_scenes or METRICS["total_prevu"]),
            "scenes": METRICS["scenes"],
            "premier_essai": METRICS["premier_essai"],
            "essais_total": METRICS["essais_total"],
            "tronques": METRICS["tronques"],
            "jetons_envoyes": METRICS["jetons_envoyes"],
            "jetons_recus": METRICS["jetons_recus"],
            "modeles": METRICS["modeles"],
            "refus": METRICS["refus"][:12],
            "duree_s": METRICS["duree_s"],
        })
        log("Bilan publié (gsapw-metrics).")
    except Exception as erreur:  # noqa: BLE001
        log("Bilan non publié : %s" % type(erreur).__name__)
    log("BILAN " + json.dumps({
        "scenes": METRICS["scenes"], "total": total_scenes,
        "premier_essai": METRICS["premier_essai"], "essais": METRICS["essais_total"],
        "tronques": METRICS["tronques"],
        "jetons": [METRICS["jetons_envoyes"], METRICS["jetons_recus"]],
        "duree_s": METRICS["duree_s"],
    }, ensure_ascii=False))


def main():
    debut_run = time.time()
    log("Récupération des scènes...")
    scenes = vercel("gsapw-source")["scenes"]
    METRICS["total_prevu"] = len(scenes)
    log("%d scène(s) à écrire (modèle %s, renfort %s, réflexion %s)." % (len(scenes), MODEL, MODEL_RETRY, THINKING))
    log("Mode détaillé : " + ("oui" if DEBUG else "non"))
    signaler("demarrage", 0, len(scenes), 0, "Animation IA : %d scène(s)" % len(scenes))
    for n, scene in enumerate(scenes, 1):
        index = scene["index"]
        utilisateur = scene["user"]
        accepte = False
        for essai in range(1, ESSAIS_SCENE + 1):
            modele = MODEL if essai == 1 else MODEL_RETRY
            METRICS["essais_total"] += 1
            METRICS["modeles"][modele] = METRICS["modeles"].get(modele, 0) + 1
            log("Scène %d/%d : tentative %d (modèle %s)" % (n, len(scenes), essai, modele))
            signaler("ecriture", n, len(scenes), essai, "Scène %d/%d : écriture" % (n, len(scenes)))
            if DEBUG:
                bloc("Consigne système (scène %d)" % n, scene["system"], "    # ")
                bloc("Consigne de la scène %d" % n, utilisateur, "    > ")
            try:
                contenu, fin_flot, usage = ecrire(scene["system"], utilisateur, model=modele)
            except Exception as erreur:  # noqa: BLE001
                log("  erreur : %s" % erreur)
                time.sleep(5)
                continue
            comptabiliser(usage)
            probleme = controle_local(contenu)
            if probleme:
                log("  contrôle local : refusé (%s)" % probleme)
                noter_refus("scène %d : %s" % (index + 1, probleme))
                signaler("refuse", n, len(scenes), essai, "Scène %d : JSON illisible" % n)
                utilisateur = (scene["user"] + "\n\n— TA RÉPONSE PRÉCÉDENTE (ILLISIBLE) —\n"
                               + contenu[:2000] + "\n\n" + probleme
                               + "\nRenvoie UNIQUEMENT l'objet JSON corrigé, sans texte autour.")
                continue
            signaler("controle", n, len(scenes), essai, "Scène %d/%d : validation" % (n, len(scenes)))
            try:
                resultat = vercel("gsapw-check", {"index": index, "content": contenu})
            except Exception as erreur:  # noqa: BLE001
                log("  contrôle indisponible : %s" % erreur)
                time.sleep(5)
                continue
            if resultat.get("ok"):
                log("  contrôle : accepté")
                accepte = True
                if essai == 1:
                    METRICS["premier_essai"] += 1
                signaler("accepte", n, len(scenes), essai, "Scène %d/%d : acceptée" % (n, len(scenes)))
                break
            log("  contrôle : refusé")
            fix = str(resultat.get("fix", ""))
            noter_refus("scène %d : %s" % (index + 1, fix))
            if DEBUG:
                bloc("Problèmes signalés par le contrôle", fix, "    ! ")
            # Le bloc refusé accompagne la correction : le modèle voit son code
            # et corrige au lieu de tout réinventer (cause n°1 d'échecs en série).
            utilisateur = (scene["user"] + "\n\n— TON BLOC PRÉCÉDENT (REFUSÉ) —\n"
                           + contenu + "\n\n" + fix)
            signaler("refuse", n, len(scenes), essai, "Scène %d/%d : corrigée" % (n, len(scenes)))
        METRICS["scenes"] += 1
        if not accepte:
            try:
                vercel("gsapw-fail", {"index": index})
            except Exception as erreur:  # noqa: BLE001
                log("  échec non signalé : %s" % erreur)
            signaler("echec", n, len(scenes), essai, "Scène %d/%d : échec" % (n, len(scenes)))
            raise RuntimeError("scène %d non écrite" % (index + 1))
        log("Scène %d/%d écrite." % (n, len(scenes)))
        time.sleep(PAUSE_SCENES)
    log("Toutes les scènes sont écrites.")
    signaler("fait", len(scenes), len(scenes), 0, "Animation IA : terminée")
    METRICS["duree_s"] = round(time.time() - debut_run, 1)
    publier_metriques(len(scenes))


if __name__ == "__main__":
    probleme = None
    try:
        main()
    except Exception as erreur:  # noqa: BLE001
        probleme = erreur
        # Bilan publié même en échec : c'est ce qui permet de suivre le taux
        # d'échec des scènes et les motifs de refus les plus fréquents.
        publier_metriques(0)
    try:
        vercel("gsapw-cleanup", {})
    except Exception as erreur:  # noqa: BLE001
        log("Nettoyage non effectué : %s" % erreur)
    if probleme:
        sys.exit("Échec : %s" % probleme)
