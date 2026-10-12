# Voix du catalogue — sources et licences

Les échantillons de référence sont générés **localement** par `scripts/voice-refs.sh` avec Piper (rhasspy/piper-voices)
et restent dans `~/.local/share/atelier/voices`. Ils ne sont pas distribués avec le dépôt.

| Voix du catalogue | Voix Piper (locuteur, décalage) | Jeu de données / licence |
|---|---|---|
| femme-claire | fr_FR-siwis-medium | SIWIS — CC-BY 4.0 |
| femme-chaleureuse, voix-aigue (+3 dt) | fr_FR-upmc-medium (jessica) | UPMC — CC-BY-SA 4.0 |
| voix-agee (−1 dt) | fr_FR-upmc-medium (pierre) | UPMC — CC-BY-SA 4.0 |
| femme-posee (−1 dt), homme-jeune (+1 dt), homme-narrateur, anonyme | fr_FR-mls-medium (12, 82, 5, 42) | Multilingual LibriSpeech (Pratap et al., 2020) — CC-BY 4.0 |
| homme-pose, homme-grave (−3 dt) | fr_FR-tom-medium | AGPL-3.0 (usage local; copyleft si le modèle est redistribué) |
| en-femme-claire | en_US-lessac-medium | licence de recherche Blizzard 2013 (non commercial) |
| en-femme-chaleureuse | en_GB-jenny_dioco-medium | « Jenny (Dioco) » — attribution requise dans un logiciel qui génère de l'audio |
| en-homme-pose, en-homme-grave (−3 dt) | en_US-ryan-high | CC BY-NC-SA 4.0 (non commercial) |
| narrateur-en | en_GB-alan-medium | redistribution douteuse (Mycroft AI); usage personnel local seulement |

Les genres des locuteurs MLS sont déduits de la hauteur médiane (F0), pas documentés par le jeu de données.
Usage personnel et local: sans restriction pratique. **Distribution ou usage commercial**: attribuer CC-BY/CC-BY-SA,
nommer « Jenny (Dioco) », et ne pas utiliser les voix non commerciales (lessac, ryan) ni alan.

Les voix IA (Seed-VC, GPL-3.0) copient le timbre d'une référence: n'ajouter que des voix dont on a le droit
(la case est obligatoire dans l'interface).
