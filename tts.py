"""Synthèse vocale RENDRAX (Edge TTS) : texte -> sortie/audio.mp3 + sortie/timings.json.

Variables d'environnement : TEXTE_FICHIER, VOIX, VITESSE, TON, SORTIE (dossier).
"""
import asyncio
import io
import json
import os
import re
import sys

import edge_tts

try:
    from mutagen.mp3 import MP3
except Exception:  # mutagen absent : durée estimée avec les timestamps
    MP3 = None

VOIX = os.environ.get("VOIX", "fr-FR-VivienneMultilingualNeural")
VITESSE = os.environ.get("VITESSE", "-5%")
TON = os.environ.get("TON", "-2Hz")
TEXTE_FICHIER = os.environ.get("TEXTE_FICHIER", "kidas-tmp/texte.txt")
SORTIE = os.environ.get("SORTIE", "sortie")
TAILLE_MAX = 1500
ESSAIS = 3

# Même validation que côté Vercel (défense en profondeur).
if not (re.fullmatch(r"[a-z]{2,3}-[A-Z]{2}-[A-Za-z]{2,40}Neural", VOIX)
        and re.fullmatch(r"[+-](\d{1,2}|100)%", VITESSE)
        and re.fullmatch(r"[+-]\d{1,3}Hz", TON)):
    sys.exit("Réglages de voix invalides.")


def decouper_phrases(texte, taille_max):
    """Coupe un long paragraphe par phrases pour rester sous taille_max."""
    phrases = re.split(r"(?<=[.!?…])\s+", texte)
    morceaux, courant = [], ""
    for ph in phrases:
        while len(ph) > taille_max:
            coupe = ph.rfind(" ", 0, taille_max)
            coupe = coupe if coupe > 0 else taille_max
            if courant:
                morceaux.append(courant.strip())
                courant = ""
            morceaux.append(ph[:coupe].strip())
            ph = ph[coupe:].strip()
        if len(courant) + len(ph) + 1 <= taille_max:
            courant += ph + " "
        else:
            if courant:
                morceaux.append(courant.strip())
            courant = ph + " "
    if courant.strip():
        morceaux.append(courant.strip())
    return morceaux


def decouper_texte(texte, taille_max=TAILLE_MAX):
    morceaux, bloc = [], ""
    for p in texte.split("\n\n"):
        p = p.strip()
        if not p:
            continue
        if len(p) > taille_max:
            if bloc:
                morceaux.append(bloc.strip())
                bloc = ""
            morceaux.extend(decouper_phrases(p, taille_max))
        elif len(bloc) + len(p) + 2 <= taille_max:
            bloc += p + "\n\n"
        else:
            morceaux.append(bloc.strip())
            bloc = p + "\n\n"
    if bloc.strip():
        morceaux.append(bloc.strip())
    return morceaux


def creer_communicate(morceau):
    try:  # edge-tts 7.x : les mots ne sont renvoyés que si on les demande
        return edge_tts.Communicate(morceau, VOIX, rate=VITESSE, pitch=TON, boundary="WordBoundary")
    except TypeError:  # edge-tts 6.x : mots par défaut
        return edge_tts.Communicate(morceau, VOIX, rate=VITESSE, pitch=TON)


async def synthetiser(morceau):
    """Un bloc -> (octets MP3, [(texte, début_s, fin_s)]) avec nouvelles tentatives."""
    derniere = None
    for essai in range(1, ESSAIS + 1):
        try:
            audio = bytearray()
            mots = []
            async for chunk in creer_communicate(morceau).stream():
                if chunk["type"] == "audio":
                    audio.extend(chunk["data"])
                elif chunk["type"] in ("WordBoundary", "SentenceBoundary"):
                    debut = chunk["offset"] / 1e7
                    mots.append((chunk["text"], debut, debut + chunk["duration"] / 1e7))
            if not audio:
                raise RuntimeError("Aucun audio reçu")
            return bytes(audio), mots
        except Exception as erreur:  # noqa: BLE001
            derniere = erreur
            print(f"  Essai {essai}/{ESSAIS} échoué : {erreur}")
            await asyncio.sleep(2 * essai)
    raise RuntimeError(f"Échec après {ESSAIS} essais : {derniere}")


def duree_bloc(donnees, mots):
    if MP3 is not None:
        try:
            return float(MP3(io.BytesIO(donnees)).info.length)
        except Exception:  # noqa: BLE001
            pass
    return max((fin for _, _, fin in mots), default=0.0)


async def main():
    with open(TEXTE_FICHIER, encoding="utf-8") as f:
        texte = f.read().strip()
    if not texte:
        sys.exit("Erreur : texte vide.")

    morceaux = decouper_texte(texte)
    print(f"Texte découpé en {len(morceaux)} bloc(s) (voix : {VOIX}).")

    audio_total = bytearray()
    items = []
    decalage = 0.0
    for i, morceau in enumerate(morceaux, 1):
        print(f"Traitement du bloc {i}/{len(morceaux)}...")
        donnees, mots = await synthetiser(morceau)
        audio_total.extend(donnees)
        for mot, debut, fin in mots:
            items.append({"texte": mot, "debut": round(decalage + debut, 3), "fin": round(decalage + fin, 3)})
        decalage += duree_bloc(donnees, mots)

    os.makedirs(SORTIE, exist_ok=True)
    with open(os.path.join(SORTIE, "audio.mp3"), "wb") as f:
        f.write(audio_total)
    with open(os.path.join(SORTIE, "timings.json"), "w", encoding="utf-8") as f:
        json.dump({"voix": VOIX, "duration": round(decalage, 3), "items": items}, f, ensure_ascii=False)
    print(f"Succès : {len(audio_total) // 1024} Ko, {decalage:.1f} s, {len(items)} repères.")


if __name__ == "__main__":
    asyncio.run(main())
