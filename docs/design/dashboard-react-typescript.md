# Dashboard P4 · analiză și implementare

## Proiectul inspectat

DriveMate separă percepția P1, contextul și siguranța P2, asistentul și vocea P3, respectiv suprafețele vizibile și simulatorul P4. Frontendul existent folosea deja React/Vite, un WebSocket la 10 Hz, video MJPEG și API-ul de voce P3. Refactorizarea păstrează aceste interfețe.

În checkoutul inspectat, `core/main.py`, `shared/contracts.py`, implementarea `integrations/contact_app` și fixture-ul canonic P2 nu sunt prezente. Simulatorul nu conține încă implementarea descrisă în plan. Acestea limitează verificarea cap-coadă; dashboardul poate fi dezvoltat independent prin simularea existentă bazată pe fixture-ul P3. Tipurile frontend sunt un model de consum cu proprietăți opționale, nu un contract backend nou.

## Rezultatul implementat

- Componentele dashboardului și sesiunea sunt în TypeScript, cu verificare `strict` înaintea buildului. Folderul de voce P3 este păstrat în JavaScript.
- Camera, starea generală și banda de performanță sunt separate de modulele selectabile. Fișa și telemetria au secțiuni proprii. Modul Compact ajustează densitatea.
- Layoutul folosește grile flexibile, coloane unice pe ecrane înguste și navigare orizontală în interiorul paginii. Camera devine compactă la scroll pe mobil. În ferestre cu înălțime mică, camera nu rămâne sticky, pentru a lăsa loc conținutului.
- Skill-ul oficial Motion a fost descărcat în `dashboard/.agent-skills/motion/` și citit înaintea implementării animațiilor. Indicatorul selecției folosește `layoutId`; schimbarea modulelor folosește `AnimatePresence`; marcajele reacției folosesc `layout`. Mișcarea este scurtă, fără overshoot, și respectă preferința utilizatorului pentru mișcare redusă.
- Scorurile, graficul și alertele rămân actualizări directe. Valorile absente apar cu „—”; zero rămâne zero; baseline zero sau absent nu produce raport; o zonă oculară necunoscută rămâne explicit necunoscută.
- Istoricul păstrează 120 de mostre și întreruperi între secvențe lipsă. Jurnalul păstrează maximum 60 de evenimente.

## Verificare și limite

Verificarea TypeScript și buildul de producție au trecut. Testele automate verifică randarea React pe date parțiale, valorile zero, referințele de reacție nevalide, ochii nesiguri și limitele bufferelor.

Controlul Chrome nu a fost aprobat în sesiunea de implementare. Layoutul responsive și interacțiunile nu au fost confirmate vizual. Înainte de demo trebuie verificate la 360, 768, 1280 și 1920 px, cu zoom 200%, tastatură și reduced motion, apoi pe serviciile reale P1–P3. Alarma, vocea, comenzile debug și camerele necesită acea integrare.

Pornire și configurare: [dashboard/README.md](../../dashboard/README.md). Skill oficial: [Motion AI Kit](https://motion.dev/docs/ai-kit).

## Revizie vizuală · Midnight Steel / Deep Horizon / Denim

Navbarul cu secțiuni este integrat în header, pe același fundal continuu ca restul dashboardului. Pe mobil, secțiunile trec pe al doilea rând al aceluiași header. Cardurile albe au fost înlocuite cu suprafețe translucide în nuanțele paletei cerute, cu contururi discrete și text deschis. Graficele și vizorul camerei folosesc accente Denim, iar avertizările păstrează culorile semantice.

Skill-urile oficiale GSAP core, React, timeline și performance sunt păstrate în `dashboard/.agent-skills/`. GSAP coordonează intrarea brandului, titlului și ramei vizorului; Motion gestionează în continuare navigarea și stările componentelor. Cele două biblioteci nu animă aceeași proprietate pe același element. GSAP folosește `useGSAP`, scope local, cleanup și `matchMedia` pentru reduced motion. Datele și alertele nu sunt întârziate de aceste tranziții.

TypeScript, cele șase teste existente și buildul de producție au trecut după integrare. Confirmarea vizuală în browser și verificarea fizică pe mobil rămân de efectuat.
## Urmărirea funcțiilor P1–P3 în dashboard

| Modul | Ce poate verifica operatorul | Dependență pentru proba live |
| --- | --- | --- |
| P1 · percepție | Imaginea șoferului și a pasagerului, fiabilitatea oculară, FPS pe cameră și latența captură → publicare la percentila 95 | Fluxurile MJPEG P1 și valorile de percepție transmise prin core. Decupajul ocular necesită un flux configurat. |
| P2 · context și siguranță | Ora ultimei stări, scorurile pe scara 0–100, întreruperile din istoric, alerta activă și ultima latență a alarmei față de ținta sub 300 ms | Mesajele de stare și evenimente de pe WebSocket. Navigarea între secțiuni păstrează sesiunea. |
| P3 · asistent | Activarea vocii, transcrierea, sugestia, pauza asistentului și jurnalul. Panoul vocal rămâne montat la schimbarea secțiunii. | Socket conectat, activare prin gest în browser și servicii audio disponibile. |

Proba pe hardware urmărește pierderea camerei, întreruperea și reluarea stării, apoi o sesiune vocală în timpul navigării. Rezultatele pe hardware se consemnează după rularea cu serviciile reale.

## Simulatorul de locație → core · implementat 21 noiembrie 2026

Harta (`#/simulator`) este simularea live a locației pentru demo. Utilizatorul construiește un traseu rutier (OSRM): primul punct este plecarea, ultimul destinația, iar punctele dintre ele sunt opriri cu tip (`fuel`, `cafe`, `pharmacy`, `supermarket`, `auto_parts`) sau puncte de trecere (`waypoint`, folosite doar pentru forma drumului). Pagina scoate **fișierul de traseu** `drivemate-route.json`, care se poate descărca, și îl trimite la core.

**Fluxul.** Dashboard → `PUT /simulator/route` (Vite face proxy către core) → `simulator.Simulator` (P4, încărcat de `core.simulation.load_simulator`) → `State.trip` la 10 Hz → engine (siguranță, scoruri, mementouri la oprire, SOS, contactul de încredere) și LLM (`assistant/summary.py`: drum, viteză, ETA, următoarea oprire cu tipul și distanța). Contractul (`shared/contracts.py`) nu se schimbă.

| Fișierul de traseu (`simulator/route.py`, `drivemate_route` v1) | |
| --- | --- |
| `origin` | plecarea, `category: "origin"` |
| `stops[]` | în ordine; ultima are `category: "destination"` (numai ea) |
| `geometry[]` | drumul OSRM, `{lat, lon}`, maximum 20 000 de puncte |
| `distance_km`, `speed_kmh`, `name`, `id`, `created_ts` | informative; `speed_kmh` setează viteza inițială |

Core respinge cu 422 și motivul: câmpuri necunoscute, coordonate în afara intervalelor sau nefinite, o oprire la peste 500 m de drum, fără destinație, id-uri duplicate. Pragurile sunt în `simulator/simulator.yaml`.

**Mișcarea** rămâne pe `/ws/ui`, cu comenzile existente: `start` (pleacă și de la o oprire), `pause`, `speed`, `time_scale`, `stop_at_next_poi` (mașina merge până la oprire și se oprește acolo; `trip.at_poi` este oprirea) și `reset` (înapoi la plecare, traseul rămâne). La destinație mașina se oprește cu `at_poi` = destinația și `eta_min` = 0. `POST /simulator/seek {"fraction"}` mută mașina pe drum, în pauză. `DELETE /simulator/route` revine la drumul demonstrativ al core-ului. `GET /simulator/route` dă traseul urmat, așa că pagina îl reîncarcă după refresh. Încărcarea și scoaterea traseului apar în jurnal (`route_loaded`, `route_cleared`).

Mașina de pe hartă este întotdeauna `State.trip.pos`, adică poziția calculată de core. Browserul nu mai simulează nimic.

**Unde e mașina, pentru LLM.** Simulatorul adaugă în `State.trip` două câmpuri suplimentare. Contractul păstrează câmpurile necunoscute (`ContractModel`), deci `shared/contracts.py` nu se schimbă:
- `trip.place`: ultimul loc trecut și următorul, cu distanțele, plus destinația, toate cu nume din fișierul de traseu. În rezumatul pentru LLM (`assistant/summary.py`) apare ca „Location: after Cluj-Napoca (12 km behind), before Turda (40 km ahead); destination Turda in 40 km”. LLM-ul nu primește coordonate, deci nu poate plasa greșit mașina. Pentru o rută cu mai multe orașe, adaugă fiecare oraș ca punct de trecere.
- `trip.attractions_ahead`: cel mult 3 obiective în următorii 40 km, cu distanța, ocolul și descrierea.

**Obiective turistice (K4).**
- **Căutare:** pagina caută automat articole Wikipedia cu coordonate la cel mult 2 km de drum (geosearch, câte o cerere pe rând). Elimină localitățile, păstrează cel mult 3 obiective la 15 km și preselectează câte unul pe porțiune, niciunul în primii 5 km.
- **Descrierea** vine din rezumatul aceluiași articol și poate fi editată.
- **Manual:** se pot bifa sau debifa obiective, sau adăuga direct pe hartă.
- **Fișierul de traseu** le duce în lista `attractions`. Core le acceptă la cel mult 5 km de drum.
- **Propunerea:** `core/attractions.py` propune obiectivul prin evenimentul obișnuit `stop_suggested`, cu `kind: "attraction"`. Condițiile sunt în `core/config/thresholds.yaml`, secțiunea `attractions`: după 5 minute de condus, mașina în mers, fără alertă, dialog sau vorbire în curs. Fiecare obiectiv se propune o singură dată, cu cel mult o propunere la 15 minute de drum, iar ținta e la 1–15 km în față.
- **Pauza de oboseală** (`pick_stop`) alege un obiectiv în locul opririi următoare, dacă niciun memento nu are nevoie de acea oprire.
- **Asistentul** întreabă „Peste 13 km e Castelul de la Gilău. Facem o pauză acolo?”. Promptul îi permite cel mult un fapt, luat din descriere.
- **„Da”** face simulatorul să conducă până în punctul de drum cel mai apropiat de obiectiv și să oprească acolo (`stop_at`). Asta se aplică acum oricărei opriri acceptate, nu doar obiectivelor.

**Limite.** `State.trip` are doar următoarea oprire și `trip.place`, nu lista completă a opririlor. Harta, rutarea și Wikipedia au nevoie de internet. Serverul public OpenStreetMap Overpass nu a răspuns din rețeaua echipei, de aceea sursa obiectivelor e Wikipedia.

**Teste.** `tests/simulator` (traseu, mișcare, opriri, destinație, seek, loc, obiective), `tests/core/test_route_api.py` (API și starea), `tests/core/test_attractions.py` (propunere, „da” → oprire, pauză), `tests/assistant/test_route_context.py` (ce vede LLM-ul), `tests/contract/test_dashboard_route.py` cu fixture-ul comun `tests/contract/fixtures/dashboard_route_file.json`, pe care testul dashboardului îl compară exact cu `routeFile(...)`.
