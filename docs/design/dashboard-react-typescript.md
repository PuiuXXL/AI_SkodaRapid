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

## Contract de integrare simulator → P2 · 21 noiembrie 2026

**Stare: propunere pentru P2, bazată pe implementarea P4 din `1e2758b`; nu este contract backend implementat sau aprobat.** `shared/contracts.py` lipsește în acest checkout. P2 rămâne proprietarul schemei canonice, al versiunii și al fixture-ului din `tests/core/fixtures/state_example.json`.

### Ce există acum în P4

Pagina `#/simulator` permite puncte pe hartă, aliniere la drum la maximum 500 m, calcul OSRM, reordonare, pornire/pauză, resetare, salt pe traseu, viteză 0–160 km/h și timp ×1/×5/×20/×100. Poziția se actualizează local aproximativ la 10 Hz. Harta și rutarea necesită internet.

`dashboard/src/Simulator.tsx` afișează și copiază următorul obiect; **nu trimite locația pe WebSocket, nu salvează un fișier JSON și nu alimentează core-ul**:

```json
{
  "source": "frontend_simulator",
  "timestamp": 1795258800.0,
  "latitude": 46.769,
  "longitude": 23.589,
  "heading_deg": 180.0,
  "speed_kmh": 118,
  "distance_km": 1.25,
  "elapsed_s": 38.14,
  "status": "moving"
}
```

| Câmp existent | Semnificație și validare pentru receptor |
| --- | --- |
| `source` | Valoare fixă `frontend_simulator`; origine sintetică, nu GPS real. |
| `timestamp` | Secunde Unix de la ceasul browserului, generate la randarea preview-ului; nu timp simulat. |
| `latitude`, `longitude` | Numere finite, grade WGS84; intervale [−90, 90], respectiv [−180, 180]. |
| `heading_deg` | Direcția segmentului curent, [0, 360), 0 = nord. Fără traseu, preview-ul folosește 0 ca valoare provizorie. |
| `speed_kmh` | Viteza configurată în deplasare; 0 în pauză, la sosire sau fără traseu. Poate fi 0 și cu `status=moving`. |
| `distance_km` | Distanța cumulată parcursă pe geometria traseului, în kilometri; resetarea/recalcularea o aduce la 0, iar saltul pe traseu o poate micșora. |
| `elapsed_s` | Secunde simulate; pauza le oprește, multiplicatorul le accelerează. La salt sunt recalculate din distanță și viteza curentă; nu reprezintă un ceas monoton. |
| `status` | `moving`, `paused` sau `arrived`. `paused` poate desemna și un singur punct fără traseu calculat. |

Fără niciun punct, preview-ul este `null`. Payload-ul nu conține geometria, distanța totală, POI-urile, multiplicatorul sau un identificator al traseului. Nu se pot deduce ETA, tipul drumului și sosirea la un POI doar din acest obiect.

### Ce are de implementat P2

1. Publică modelul de intrare pentru locația simulată în `shared/contracts.py`, cu validările de mai sus. Păstrează compatibilitatea contractului existent; câmpurile noi din starea publicată sunt opționale, cu valori implicite. Actualizează împreună versiunea și fixture-ul canonic.
2. Convenție propusă, de confirmat cu P4: mesaj browser → core pe `/ws/ui`, `{"type":"simulator_location","data":{...obiectul de mai sus...}}`. Acest tip nu este recunoscut sau transmis încă de implementarea curentă. Validează mesajul înainte de a-l folosi și acceptă intrarea sintetică numai în modul de simulare configurat explicit în core; selectarea sursei UI nu este suficientă.
3. Mapează în `State.trip` câmpurile deja prevăzute în plan: `pos.lat ← latitude`, `pos.lon ← longitude`, `speed_kmh ← speed_kmh`, `elapsed_min ← elapsed_s / 60`. Nu transforma automat `paused` în `stopped` sau `arrived` în `at_poi`: pauza redării și sosirea la capătul traseului nu confirmă o oprire la un POI.
4. Decide explicit sursa activă între simulatorul Python `Simulator.tick()` și intrarea din browser; o singură sursă produce `trip` la un moment dat. Definește comportamentul la deconectare/date vechi și la resetare/salt, fără a continua să folosești viteza veche ca informație proaspătă.
5. Returnează starea canonică spre UI în formatul deja consumat, `{"type":"state","state":{...}}`, la 10 Hz, cu `ts` și `seq` generate de core. Regulile de siguranță, riscul, cauza, alarmele și SOS rămân în P2; payload-ul browserului nu le stabilește.
6. Pentru ETA, POI-uri și tipul drumului, stabilește separat cu P4 transferul metadatelor traseului sau calculul lor în simulatorul Python. Păstrează valorile necunoscute explicite până când există o sursă.

### Ce rămâne de implementat P4 după stabilirea interfeței

- Trimiterea mesajelor de locație pe socketul existent, limitată la 10 Hz, plus actualizări explicite la pauză, resetare, salt și sosire; timestamp nou la expediere. Oprește transmiterea când sursa sintetică este dezactivată.
- Separarea comenzilor locale de conexiunea Live: resetarea traseului nu trebuie să reconecteze WebSocketul sau să șteargă istoricul Live; editarea traseului nu trebuie să blocheze datele demo fără posibilitate de reluare.
- Detectarea trecerii peste pragurile evenimentelor demo la ×20/×100; egalitatea exactă actuală sare peste ele.
- Trimiterea geometriei/metadatelor numai după convenirea unei extensii, dacă P2 are nevoie de ele. Modificările de navigare, graficele și straturile hărții nu cer câmpuri backend noi.

### Criterii de acceptare P2 + P4

- Un mesaj valid actualizează `trip.pos`, viteza și timpul în următorul `state`; un mesaj invalid nu închide fluxul de stare și nu modifică datele valide precedente.
- Pornirea, pauza, viteza 0, sosirea, saltul înapoi și resetarea au comportament verificat; absența sau întreruperea sursei este tratată explicit.
- Resetarea în UI păstrează conexiunea și istoricul Live; sursa de locație nu schimbă datele P1 sau autoritatea regulilor P2.
- Teste pentru coordonate-limită, valori nefinite, statut invalid, date vechi, schimbarea sursei și mesaje vechi după resetare. Înainte de streaming trebuie convenit un identificator de sesiune/revizie sau alt mecanism pentru respingerea mesajelor vechi; preview-ul actual nu îl conține.
- Proba cap-coadă și confirmarea P2/P4 sunt încă restante. Cele 8 teste frontend și buildul trec, dar nu validează această interfață propusă.

