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

## Strategi: pris, ikke ytelser

Zaim 10.09.2026: "I want to pay the lowest amount possible. The real
measurement is how much money can i save. Not what other services i get."

Ytelsesstrategien er derfor lagt vekk. Alt går på kroner.

| Trinn | Bud | Argument |
|---|---|---|
| Åpning | 279 000 | 30 000 under, forankrer lavt |
| 2 | 291 000 | Kun etter mottilbud |
| 3 | 297 000 | På nivå med 473616501 |
| Siste | 298 600 | Presist tall, signaliserer tak |

Walk-away 299 500. Over det er 473616501 et bedre kjøp på rene tall.

Realistisk landing **295 000-300 000**, altså 9 000-14 000 spart. Bilen er
riktig priset, og 9 dagers liggetid gir lite tidspress, så det er taket på hva
ren prispressing gir her.

## Det største enkelttallet

Hvis målet er kroner spart og ikke denne spesifikke bilen, er det verdt å si
én gang: [475873426](https://www.finn.no/mobility/item/475873426) ligger på
245 000, er fritatt omregistrering og har vinterdekk. Det er **64 000 kr**
billigere enn 461004495 før forhandling i det hele tatt.

Valget av bil betyr med andre ord fem ganger mer enn forhandlingen på denne
bilen. Sagt én gang, så går vi videre med 461004495 som avtalt.

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

## Bekreftet fra annonsen

Annonsetittelen oppgir **Design**-nivå. Bilen har altså elektrisk bakluke og
15,6" roterbar skjerm, som er de eneste reelle utstyrsforskjellene mellom
Comfort og Design. Utstyrslisten på Finn nevner ingen av delene, noe som
bekrefter at korte utstyrslister ikke kan leses som mangler.

## Status

**10.09.2026 09:20 - melding 1 sendt** til STAR BIL AS via Finn.
Spørsmål om batterirapport (SOH), service, to nøkler, mønsterdybde og
transport fra Skien. Ingen tall nevnt. Telefonnummer ikke oppgitt.

Finn bekreftet: "Meldingen er sendt. Selgeren vil kontakte deg så snart som
mulig."

Neste steg: melding 2 (full pris mot ytelser) når de svarer. Ligger klar i
`SELLER_MESSAGES.md`.
