"""Filtres ffmpeg des effets de voix (sans modèle): repli sans GPU et post-traitement des voix IA."""

FX = {
    "grave": ("Plus grave", "Hauteur -4 demi-tons, timbre conservé", "rubberband=pitch=0.79:formant=preserved"),
    "aigu": ("Plus aigu", "Hauteur +4 demi-tons, timbre conservé", "rubberband=pitch=1.26:formant=preserved"),
    "helium": ("Hélium", "Voix de dessin animé", "rubberband=pitch=1.6:formant=shifted"),
    "demon": ("Démon", "Très grave et sombre", "rubberband=pitch=0.62:formant=shifted,lowpass=f=4500"),
    "robot": ("Robot", "Modulation en anneau 45 Hz", "aeval=val(0)*sin(2*PI*45*t):c=same,highpass=f=120"),
    "radio": ("Radio", "Bande étroite, compressée", "highpass=f=300,lowpass=f=3400,acompressor=threshold=0.1:ratio=6,volume=1.4"),
    "cave": ("Caverne", "Écho long", "aecho=0.8:0.88:70|140:0.4|0.25"),
}
# post-traitements appliqués après la conversion IA
POST = {
    "age": "tremolo=f=5.5:d=0.22,highpass=f=120,lowpass=f=5200",
}


def chain(fx_id: str) -> str:
    if fx_id in FX:
        return FX[fx_id][2]
    if fx_id in POST:
        return POST[fx_id]
    raise KeyError(fx_id)
