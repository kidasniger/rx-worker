# rx-worker — moteur de rendu RENDRAX

Worker exécuté sur **GitHub Actions**. Il reçoit des déclenchements `workflow_dispatch`
depuis l'API RENDRAX (rendrax.vercel.app), télécharge les sources depuis le stockage
privé Backblaze B2, produit les médias, puis les publie dans B2 via des URL pré-signées.
**Aucun secret n'est stocké ici** : chaque échange est authentifié par un jeton OIDC
GitHub (audience `https://rendrax.vercel.app/kidas-render`), vérifié côté Vercel
dépôt par dépôt, workflow par workflow et run par run.

## Contenu

| Élément | Rôle |
|---|---|
| `html2mp4.py` | CLI « HTML animé → MP4 » : rendu image par image + audio assemblé par FFmpeg (Termux ou Linux, menu interactif sans argument). |
| `h2m/` | Bibliothèque du moteur : profils reconnus (kidas, editpro, musicpro, voicevideo, gsapvideo, générique), pilotage Chromium via CDP, encodage, synchronisation A/V, filigrane, progression. |
| `tts.py` | Synthèse vocale (Edge TTS) : texte → `audio.mp3` + `timings.json` (horodatage mot par mot). |
| `scripts/safe_extract_zip.py` | Extraction ZIP défensive : 50 Mo d'archive, 2 000 entrées, 250 Mo décompressés, 100 Mo par fichier, refus des liens symboliques et chemins suspects. |
| `.github/workflows/render.yml` | Rendu vidéo : télécharge la source (`/api/runner-source`), rend via `html2mp4.py`, génère la miniature, publie MP4 + miniature dans B2 (`/api/videos?action=upload-url` puis `publish`), poste la progression, nettoie. Timeout 90 min. |
| `.github/workflows/tts.yml` | Voix : télécharge le texte (`/api/videos?action=tts-source`), lance `tts.py`, publie MP3 + repères dans B2 (`tts-upload-url`, `tts-publish`), nettoie. Timeout 30 min. |

## Dépendances système

- Python 3.12 + `websocket-client`, `Pillow` (+ `edge-tts`, `mutagen` pour la voix)
- Chromium (5 noms testés) et FFmpeg/ffprobe — installés explicitement par les workflows

## Utilisation locale (Termux/Linux)

```bash
python html2mp4.py                      # menu interactif sur le dossier du script
python html2mp4.py --file page.html     # conversion directe
python html2mp4.py --fps 24 --scale 0.5 --preview
python tts.py                           # via les variables TEXTE_FICHIER, VOIX, VITESSE, TON, SORTIE
```

Internet est nécessaire pendant le rendu (React, GSAP et polices chargés depuis des CDN).

## Liens

- Site : https://rendrax.vercel.app/
- Dépôt applicatif : https://github.com/kidasniger/RENDRAX (privé)
