# Valuing a listing

Never name a number you cannot derive. The derivation is also the argument, so
doing this properly gives you the message for free.

## Method

**1. Build the comparable set.**
Same model, ±1 model year, mileage within roughly ±50%. Include dealer and
private but keep them labelled: the legal position differs and so should the
price. Ten cars is a set; three is an anecdote.

**2. Fit price against mileage.**
With enough points, a linear fit gives kr per km and an intercept. With few
points, just rank them and look for the car that is out of line. You are not
after statistical rigour, you are after a number the seller cannot dismiss.

Practical shortcut for a thin set: take the median price of the set, then
adjust by the mileage gap times the set's kr/km slope.

**3. Adjust for condition and documentation.**
Subtract the concrete costs from `leverage.md`: tyres, discs, missing cables,
missing winter tyres, absent service history, absent SOH report.

**4. Adjust for seller type.**
A dealer car carries 5 years reklamasjonsrett with 2 years reversed burden of
proof. A private car carries 2 years with the burden on you. That gap is worth
real money on an EV. Do not compare a dealer price to a private price as if
they were the same product.

**5. Add the fees.**
Omregistrering, roughly 4 500-5 000 kr in this class. Any inspection you will
pay for. Any immediate work the car needs. This total is the number that
matters and the only one worth negotiating.

**6. Set the three numbers.**
Target from steps 2-4. Opening at 80-85% of target in a Norwegian used market.
Walk-away where the second-best car in the set becomes better value on total
cost.

## Worked example

Set of five 2023-2024 Atto 3 under 30 000 km, September 2026:

| Listing | Year | Km | Asking | Seller |
|---|---|---|---|---|
| 467995724 | 2024 | 27 903 | 299 000 | — |
| 475873426 | 2023 | 20 600 | 245 000 | Dealer |
| 461004495 | 2024 | 10 250 | 309 000 | — |
| 473616501 | 2024 | 12 193 | 299 500 | — |
| 474820076 | 2024 | 27 518 | lease takeover | Private |

Reading it: the three 2024 cars sit in a 10 000 kr band spanning 10 250 to
27 903 km. The market is not pricing mileage at all in this band, which means
either the high-mileage car is overpriced or the low-mileage ones are
underpriced. On a set this small, assume the former and open there.

The 2023 dealer car at 245 000 is 54 000 kr below the 2024 cars for one model
year and 7 000 fewer km than the highest. That is the value outlier, and the
dealer's 5-year reklamasjonsrett makes it more attractive still, not less.

Conclusion: 467995724 at 299 000 is the weakest value in the set despite
scoring well on equipment, and 475873426 at 245 000 is the strongest. Equipment
score is not value. Rank on total cost, not on feature count.

## Cross-checks

- **Rebil** publishes asking prices on its own inventory at
  `app.rebil.no`. Small stock, but independent of finn.
- **Nettbil** auction results indicate what dealers actually pay, which is the
  floor beneath any dealer asking price.
- **Elbilradar** publishes used EV market statistics.
- The `atto_listings.json` produced by `atto_finder.py` in this repo is the
  living version of the comparable set. Read it before pricing anything.

## The trap

Equipment score and value are different axes and they frequently point in
opposite directions. A well-equipped car at a bad price is a bad buy. Compute
value first, then use equipment to break ties between similarly-priced cars.

The first pass of this project ranked purely on equipment score and put the
most expensive car in the set at the top. Do not repeat that.
