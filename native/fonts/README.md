# Fonts for the native app

The same four faces as the web console, as complete desktop fonts: one file
per weight, every character (accented names included), named so that
asking for a weight gets it.

The console's web-font files are not used here: each weight is split in two
("latin" and "latin-ext") under one family name, and Qt keeps only one of
the pair, so a bold heading came out with one letter bold and the rest
regular.

| Face | Weights | From |
|---|---|---|
| IBM Plex Mono | 400 500 600 | google/fonts `ofl/ibmplexmono` (static files as published) |
| Inter | 400 500 600 | google/fonts `ofl/inter/Inter[opsz,wght].ttf`, instanced at opsz 14 |
| Schibsted Grotesk | 400 500 600 | google/fonts `ofl/schibstedgrotesk/SchibstedGrotesk[wght].ttf` |
| Newsreader | 400 500 600, italic 400 | google/fonts `ofl/newsreader/Newsreader*[opsz,wght].ttf`, instanced at opsz 16 |

Variable fonts were cut to fixed weights with fontTools
(`varLib.instancer.instantiateVariableFont(..., updateFontNames=True)`):
Qt otherwise draws only a variable font's default weight.

All four are under the SIL Open Font License 1.1 (the OFL-*.txt files here).
