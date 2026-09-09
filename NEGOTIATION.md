# BYD Atto 3 - forhandlingsnotat

Mål: [461004495](https://www.finn.no/mobility/item/461004495) - STAR BIL AS, Skien.
Oppdatert 2026-09-10. Metode: `.claude/skills/car-negotiation/`.

## Bilen

| | |
|---|---|
| År / km | 2024 / 10 250 km (lavest i utvalget) |
| Pris | 309 000 kr, hvorav 7 505 kr omregistrering |
| Farge | Grå metallic |
| Selger | STAR BIL AS, Skien. **Merkeforhandler**, 48 mnd garanti |
| Garanti | Nybilgaranti i behold |
| Dekk | **Sommer- og vinterdekk, begge på aluminiumsfelg** |
| Utstyr | Elektrisk sete, helskinn, navigasjon, ryggekamera, p-sensor foran og bak, adaptiv cruise, nøkkelløs start, oppvarmede forseter |
| Liggetid | 9 dager |

## Rettelse: bilen er bedre priset enn modellen min sa

Verdimodellen i `atto_finder.py` regnet kr/km på tvers av både 2023- og
2024-biler, og blandet dermed modellår inn i kilometerprisen. Tallet
"+28 000 mot marked" var et artefakt.

Riktig sammenligning er de tre 2024-bilene mot hverandre:

| Bil | Pris | Km | Vinterdekk | Garanti |
|---|---|---|---|---|
| 467995724 | 299 000 | 27 903 | Nei | Rest av nybilgaranti |
| 473616501 | 299 500 | 12 193 | Nei | Ikke oppgitt |
| **461004495** | **309 000** | **10 250** | **Ja, på alufelg** | Nybilgaranti, merkeforhandler |

Vinterdekk på alufelg er verdt 10 000-15 000 kr. Trekker man fra 12 000 ligger
461004495 reelt på **297 000**, altså billigst av de tre og ikke dyrest.

Bilen er med andre ord riktig priset. Det betyr lite rom på pris, og at
strategien bør flyttes fra kroner til ytelser.

## Strategi: be om ytelser, ikke avslag

Forhandlere beskytter overskriftsprisen langt hardere enn de beskytter en
service eller en transport. På en bil som allerede er riktig priset er det
her pengene faktisk ligger.

1. **Batterirapport (SOH)** fra BYD-verksted. Koster dem lite, verdt mye.
2. **Fersk service** før overlevering. 3 000-6 000 kr.
3. **Transport fra Skien.** 3 000-6 000 kr.
4. **Ekstra nøkkel** hvis det bare følger én. 3 000-5 000 kr.
5. **Full lading og komplette ladekabler** ved henting.

Samlet 10 000-20 000 kr i reell verdi uten å røre prisen. Forhandleren kan si
ja uten å innrømme at prisen var feil, og det er nettopp derfor det virker.

## Prisstige

Brukes bare hvis de avviser ytelsene. Komprimert Ackerman. 9 dagers liggetid
gir lite tidspress, så åpningen kan ikke være for lav:

| Trinn | Bud |
|---|---|
| Åpning | 289 000 |
| 2 | 297 000 |
| 3 | 301 000 |
| Siste | 302 400 |

Realistisk landing **299 000-303 000** levert, eller full pris med ytelsene
over. Walk-away 305 000 hvis de ikke gir noe som helst.

## Brekkstenger

- **467995724** ligger på 299 000 og har ligget ute i **66 dager**. Konkret,
  billigere, kan nevnes ved finnkode. Sterkeste enkeltbrekkstang vi har.
- **475873426** ligger på 245 000, er fritatt omregistrering og har også
  vinterdekk. 64 000 kr billigere, én årgang eldre. Reelt alternativ.
- **Evo-facelift** presser 2024-restverdier.
- **Månedsslutt** nærmer seg. Tim siste bud mot det.

## Ikke bruk disse

- Soltak, elektrisk sete, varmepumpe, Blade-batteri. Alt er standard.
- "Totalpris levert". De 309 000 inkluderer allerede omregistrering. Å kreve
  det som en innrømmelse viser at annonsen ikke er lest.
- Kilometerstand. Denne bilen har lavest km i utvalget. Argumentet peker
  motsatt vei.

## Status

Ingen meldinger sendt. Utkast i `SELLER_MESSAGES.md`.
