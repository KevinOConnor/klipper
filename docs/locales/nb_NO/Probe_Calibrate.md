This document describes the method for calibrating the x, y, and z offsets of an
"automatic z probe" in Klipper. This is useful for users that have a
`[probe]` or `[bltouch]` section in their config file.

# Kalibrering av probeforskyvning for X og Y

To calibrate the X and Y offset, navigate to the OctoPrint "Control" tab, home
the printer, and then use the OctoPrint jogging buttons to move the head to a
position near the center of the bed.

Place a piece of blue painters tape (or similar) on the bed underneath the
probe. Navigate to the OctoPrint "Terminal" tab and issue a PROBE command:

```
PROBE
```

Merk tapen akkurat under proben (eller bruk en lignende metode for å merke
posisjon på bunnplaten).

Utfør en «GET_POSITION»-kommando og ta vare på verktøyhodets XY-posisjon, som
rapportert av kommandoen. For eksempel hvis man ser:

```
Recv: // toolhead: X:46.500000 Y:27.000000 Z:15.000000 E:0.000000
```

vil man registrere en X-probeposisjon på 46,5 og en Y-probeposisjon på 27.

Etter å ha registrert probeposisjon, send en rekke G1-kommandoer til tuten er
direkte over merket på bunnplaten. For eksempel kan man utføre:

```
G1 F300 X57 Y30 Z15
```

for å flytte tuten til en X-posisjon på 57, og Y-posisjon på 30. Når man finner
posisjonen direkte over merket, kan man bruke «GET_POSITION»-kommandoen for å
rapportere den posisjonen. Dette er tut-posisjonen.

«x_offset» er dermed «nozzle_x_position - probe_x_position» og «y_offset» er
«nozzle_y_position - probe_y_position». Oppdater printer.cfg-filen med angitte
verdier, fjern tape/merker fra bunnplaten, og kjør så en «RESTART»-kommando slik
at de nye endringene anvendes.

# Kalibrering av probeforskyvning for Z

Å angi nøyaktig z_offset for proben er kritisk for nøyaktige utskrifter.
z_offset er avstanden mellom tuten og bunnplaten når proben utløser. Klipper
sitt «PROBE_CALIBRATE»-verktøy kan brukes til å hente denne verdien. Den vil
kjøre en automatisk probe for å måle probens Z-utløserposisjon og så starte en
manuell probe for å hente Z-høyde for tuten. Probens z_offset vil så bli regnet
ut basert på disse målingene.

Start ved å nullstile skriveren og så flytte hodet til en posisjon nær midten av
bunnplaten. Gå til «Terminal»-fanen i OctoPrint og kjør
«PROBE_CALIBTRATE»-kommandoen for å starte verktøyet.

Verktøyet vil utføre en automatisk probe, løfte hodet, flytte tuten over stedet
for probingspunkt, og starte det manuelle probeverktøyet. Hvis tuten ikke
flytter til en posisjon over det automatiske probepunktet, vil «ABORT» avslutte
det manuelle probeverktøyet og utføre kalibrering av XY-probeforskyvning
beskrevet ovenfor.

Once the manual probe tool starts, follow the steps described at ["the paper
test"](Bed_Level.md#the-paper-test)) to determine the actual distance between
the nozzle and bed at the given location. Once those steps are complete one can
`ACCEPT` the position and save the results to the config file with:

```
SAVE_CONFIG
```

Merk at hvis endringen gjøres for skriverens bevegegelsessystem,
varmepunktsposisjon, eller probeposisjonen, vil den invalidere resultatet av
«PROBE_CALIBRATE».

Hvis proben har en X- eller Y-forskyvning av bunnplatens helning (f.eks. ved
justering av bunnplateskruer, vil det å kjøre «DELTA_CALIBTRATE»,
«Z_TILT_ADJUST», «QUAD_GANTRY_LEVEL», eller lignende) vil den invalidere
resultatet av «PROBE_CALIBRATE». Etter å ha gjort noen av justeringene ovenfor,
vil man måtte kjøre «PROBE_CALIBRATE» igjen.

Hvis resultatet av «PROBE_CALIBRATE» invalideres, vil forrige
[bunnplatemaske](Bed_Mesh.md)-resultater innhenten under probingen også
invalideres. Hvis så er tilfelle må man kjøre «BED_MESH_CALIBRATE» igjen etter
rekalibrering av proben.

# Gjentaksbarhetssjekk

Etter kalibrering av probens X, Y, og Z-forskyvning, er det en god idé å
bekrefte at proben gir reproduserbare resultater. Start ved å nullstille
skriveren, og så flytte hodet til en posisjon nær midten av bunnplaten. Gå til
«Terminal»-fanen i OctoPrint og kjør «PROBE_ACCURACY»-kommandoen.

Denne kommandoen vil kjøre proben ti ganger og gi et resultat lignende følgende:

```
Recv: // probe accuracy: at X:0.000 Y:0.000 Z:10.000
Recv: // and read 10 times with speed of 5 mm/s
Recv: // probe at -0.003,0.005 is z=2.506948
Recv: // probe at -0.003,0.005 is z=2.519448
Recv: // probe at -0.003,0.005 is z=2.519448
Recv: // probe at -0.003,0.005 is z=2.506948
Recv: // probe at -0.003,0.005 is z=2.519448
Recv: // probe at -0.003,0.005 is z=2.519448
Recv: // probe at -0.003,0.005 is z=2.506948
Recv: // probe at -0.003,0.005 is z=2.506948
Recv: // probe at -0.003,0.005 is z=2.519448
Recv: // probe at -0.003,0.005 is z=2.506948
Recv: // probe accuracy results: maximum 2.519448, minimum 2.506948, range 0.012500, average 2.513198, median 2.513198, standard deviation 0.006250
```

Ideally the tool will report an identical maximum and minimum value. (That is,
ideally the probe obtains an identical result on all ten probes.) However, it's
normal for the minimum and maximum values to differ by one Z "step distance"
or up to 5 microns (.005mm). A "step distance" is
`rotation_distance/(full_steps_per_rotation*microsteps)`. The distance between
the minimum and the maximum value is called the range. So, in the above example,
since the printer uses a Z step distance of .0125, a range of 0.012500 would be
considered normal.

Hvis resultatet av testen viser en spennviddeverdi høyere en 25 mikrometer
«0,025 mm) vil proben ikke ha nok nøyaktighet for typiske
bunnplateniveleringsprosedyrer. Det kan være mulig å justere probehastighet
og/eller probestarthøyde for å forbedre gjentagbarheten for proben.
«PROBE_ACCURACY»-kommandoen lar deg kjøre tester med forskjellige parameter for
å se deres innvirkning. Sjekk «[G-kodedokumentet](G-Codes.md)» for flere
detaljer. Hvis proben generelt innhenter reproduserbare resultater, men har et
sjeldent avvik nå og da, kan det være mulig å ta høyde for dette ved å bruke
flere samplinger for hver probe. Les beskrivelsen av probens
«sample»-oppsettsparameter i «[oppsettsreferansen](Config_Reference.md#probe)»
for flere detaljer.

Hvis probehastighet, samplingsantall, eller andre innstillinger trengs, kan du
oppdatere skriverens printer.cfg-fil og kjøre «RESTART»-kommandoen. Hvis dette
gjøres er det en god idé å også [kalibrere z_offset](#calibrating-probe-z-
offset) igjen. Hvis reproduserbare resultater ikke kan demonstreres, så bruker
du ikke proben for bunnplatenivelering. Klipper har flere manuelle probeverktøy
som kan brukes istedenfor. Sjekk «[Bunnplatenivådokumentet](Bed_Level.md)» for
flere detaljer.

# Posisjonsbiassjekk

Noen prober kan ha et systemisk bias som forringer resultatet for en probe for
gitte verktøyhodeposisjoner. For eksempel, hvis proben er litt skjev når den
flytter seg langs Y-aksen, kan dette gi høyere rapportert hastighet på
forskjellige Y-posisjoner.

Dette er et vanlig problem med proner på delta-skribere, dog kan det inntreffe
på alle skrivere.

Man kan se etter posisjonsbias ved å bruke «PROBE_CALIBRATE»-kommendoen for å
måle probens z_offset ved forskjellige X- og Y-posisjoner. Ideelt vil probens
z_offset være en kosntant verdi for hver skriverposisjon.

For delta-skrivere, kan du prøve å måle z_offset på en posisjon nær A-tårnet, på
en posisjon nær B-tårnet, og på en posisjon nær C-tårnet. For cartesian, corexy,
og lignende skrivere, kan du prøve å måle z_offset på posisjoner nær de fire
hjørnene av bunnplaten.

Før du starter testen, kalibrerer du først probens X, Y og Z-forskyvning som
angitt i begynnelsen av dette dokumentet. Deretter nullstiller du skriveren og
navigerer til første XY-posisjon. Følg stegene i [kalibrering av
probeforskyvning for Z](#calibrating-probe-z-offset) og kjør
«PROBE_CALIBRATE»-kommandoen, «TESTZ»-kommandoene, og «ACCEPT»-kommandoen, uten
å kjøre «SAVE_CONFIG». Registrer rapportert z_offset. Gå så til de andre XY-
posisjonene, gjenta disse «PROBE_CALIBRATE»-stegene, og registrer rapportert
z_offset.

Hvis forskjellen mellom minste rapporterte z_offset og største rapporterte
z_offset er større enn 25 mikrometer (0,025 mm) passer ikke proben for bruk i
typiske bunnplateniveleringsprosedyrer. Sjekk
«[Bunnplatenivådokumentet](Bed_Level.md) for manuelle probealternativer.

# Temperaturbias

Mange prober har et systemisk bias der probing under forskjellige temperaturer.
For eksempel kan proben alltid utløse ved en lavere høyde når den er i høyere
temperatur.

Det anbefales å kjøre bunnplateniveleringsverktøyene i gjevn temperatur for å ta
høyde for biaset. For eksempel kan du alltid kjøre verktøyene når skriveren er i
romtemperatur, eller alltid kjøre verktøyene etter at skriveren har nådd
driftstemperatur. Uansett er det en god idé å vente flere minutter etter at
ønsket temperatur er nådd, slik at apparatet fungerer som det skal ved ønsket
temperatur.

For å sjekke temperaturbias, start med skriveren i romtemperatur og nullstill
skriveren, flytt hodet til et sted nær midten av bunnplaten, og kjør
«PROBE_ACCURACY»-kommandoen. Registrer resultatet. Deretter varmer du opp
skrivertuten og bunnplaten til skrivetemperatur, og kjører «PROBE_ACCURACY»
(uten å nullstille eller skru av stepper-motorene). Ideelt vil kommandoen gi
identiske resultater. Som ovenfor, er det nødvendig å være oppmerksom på at hvis
proben har et temperaturbias, vil det være bedre å alltid bruke den ved gjevn
temperatur.
