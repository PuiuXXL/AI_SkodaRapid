# DriveMate · plan de design pentru dashboard

Propunere P4 pentru aprobare. Publicul este pasagerul și juriul, pe laptopul de demo. Ecranul de monitorizare are două repere permanente, imaginea șoferului și performanța. Harta și simularea au un spațiu separat. Scopul primei versiuni este să poți urmări un eveniment de la imagine și semnal până la decizie și răspuns.

## Referințe și decizii

| Observație | Aplicare propusă |
|---|---|
| Tesla Model 3 menține starea vehiculului într-o zonă dedicată și afișează informații contextuale. [Manual Tesla](https://www.tesla.com/ownersmanual/model3/en_my/GUID-80B80D48-E3A9-4857-864B-F4CC9B56FD7E.html) | Poziția camerei și a alertei rămâne predictibilă când deschizi un detaliu. |
| IBM Carbon acordă cea mai mare suprafață și cel mai mare contrast informației prioritare. [Carbon Dashboards](https://carbondesignsystem.com/data-visualization/dashboards/) | Camera și propoziția despre starea actuală domină. Performanța ocupă primul rând, cu cifre lizibile. |
| NN/g descrie dezvăluirea progresivă a detaliilor, iar GOV.UK documentează un control de detalii cu etichetă explicită. [NN/g](https://www.nngroup.com/articles/progressive-disclosure/) · [GOV.UK](https://design-system.service.gov.uk/components/details/) | Fiecare modul are o întrebare, două sau trei valori mari și o deschidere cu nume precis, de exemplu „Calitatea semnalului ocular”. Alarma și pierderea monitorizării rămân la vedere. |
| WCAG cere și alte indicii în afara culorii și contrast suficient pentru text. [Culoare](https://www.w3.org/WAI/WCAG22/Understanding/use-of-color.html) · [Contrast](https://www.w3.org/WAI/WCAG22/Understanding/contrast-minimum.html) | Linii identificabile prin etichetă și stil, erori prin pictogramă și text. Țintă 4,5:1 pentru text normal. Verificare pe fundalul cel mai deschis al imaginii video. |
| Face Landmarker poate furniza repere faciale pe cadre video. [Documentația Google](https://ai.google.dev/edge/mediapipe/solutions/vision/face_landmarker) | Refolosim geometria calculată de P1 dacă o poate expune. Afișarea unui contur pe ochiul real cere corespondență cu același cadru. |

În ui_example.mp4, cadrele de la aproximativ 2, 7 și 13 s trec de la un indicator izolat la o compoziție cu imagine anatomică mare și grupuri mici de măsurători. Preluăm relația imagine–măsurătoare. În Screen Recording, cadrele de la aproximativ 2, 10 și 16 s folosesc o suprafață întunecată și o linie fină care urmărește forma unui far. Aceasta inspiră marcajul discret din vizor. În imaginile statice, Cardeva apropie eticheta de obiect, exemplul pastel separă bine figurile principale, iar exemplele întunecate mențin densitatea în panouri secundare. Pentru proiector alegem suprafețe mate, etichete opace și spațiere constantă.

## Compoziție

Pentru 1440 × 900 propunem o margine de 32 px, o bandă de performanță compactă, apoi două coloane aproximativ 38/62. Camera șoferului rămâne ancorată în stânga. Camera pasagerului primește o previzualizare proprie sub ea. În dreapta apar starea generală, scurtă explicație și previzualizări pentru „Privire”, „Starea șoferului”, „Reacție”, „Cabină” și „Asistent”. Deschiderea unei secțiuni păstrează banda și camera. Pe ecrane înguste camera devine un vizor compact deasupra conținutului. Verificăm inclusiv laptop la 1366 × 768 și 200% zoom.

Paletă propusă: fond porțelan #F1F3F0, cerneală #172522, grafit pentru cameră, petrol #116C63 pentru selecție. Chihlimbar pentru degradare, roșu pentru alarme. Instrument Sans pentru titluri, IBM Plex Mono cu cifre tabulare pentru măsurători. Etichetele video au fundal opac. Mișcarea este rezervată semnalelor reale. Graficul are 120 de puncte, aproximativ 12 secunde la 10 Hz, cu timpul efectiv pe axă.

## Inventar de proiectare

Contract de referință: planul §7 și tests/assistant/fixtures/state_example.json. Exemplul P3 este provizoriu. Confirmarea datelor de integrare îi revine P2. Valorile locale sau opționale se afișează doar dacă producătorul le furnizează cu semnificația documentată.

| Modul | Indicatori principali și reprezentare | Al doilea nivel și sursă |
|---|---|---|
| Performanță | FPS procesare șofer/pasager, ultima latență a alarmei în ms. Ultima alarmă are ținta <300 ms. | perf.cameras cu captură, procesare și cadre pierdute. p50/p95 pe model când există, CPU/GPU %, RAM MB. LLM primul token și total, STT până la text, TTS până la sunet, mesaj până la voce. Precizăm capetele fiecărei latențe. |
| General | Propoziție scurtă despre starea primită, risc 0–3, alertă și sursa LIVE/SIMULAT. | assessment, safety, cause, ts și seq. Ultima stare, permisiune LLM, viteză și ETA ca text. Un eveniment visual_cue accentuează discret rama camerei. |
| Ochi și privire | Vizor optic, zona privirii, PERCLOS pe 60 s și timpul curent în afara drumului. | driver.eyes cu EAR fără unitate, ochiul folosit, fiabilitate, clipire în ms. driver.gaze cu încredere, sursă, VATS pe 60 s și entropie când există. Seria EAR folosește goluri între mostre pierdute. În detalii pot apărea closed_ms, blink_rate, squint, long_closure și open_baseline după confirmarea câmpurilor și unităților. |
| Starea șoferului | Atenție, oboseală și dezinteres pe aceeași scară 0–100, trei linii etichetate. | assessment și cause. Explicația cauzei, ținta, sursele, priviri pe 30 s, căscat, cap înclinat, yaw/pitch/roll în grade, telefon și sursa sa. Metri orbi la ultimul episod și totalul sesiunii. |
| Reacție și input | Trei rânduri comparabile pentru privire, voce și gest. Fiecare are timp în ms, reper personal și marcaj pentru ultima reacție. | driver.reaction cu baseline_ms, missed și response_rate_10min. interaction.last_input, persoana, canalul, rezultatul, ora și dialog deschis/închis. La reper absent apare „Se stabilește referința”. |
| Cabină și telefon | Cine este prezent, cine vorbește, mesaje în așteptare. | occupants, passenger, conversation, phone, messages, reminders și media. Loc, origine detectată/declarată, treaz/adormit, telefon ținut de pasager, baterie, motivul amânării, memento și următoarea oprire relevantă. |
| Asistent și evenimente | Ultima sugestie textuală, starea vocii și sursa REGULĂ/LLM. Cronologie cu ore. | Mesajele speak/event, interaction, assistant.muted_until, intervenția, efectul, canalul și latența. Tasta D trimite comanda debug prin core. |
| Comparație și fișă | Două contoare A/B, mesaje hands-free, cel mai lung interval concentrat. | ab, blind_m, scorecard și intervention. Reacții față de referință, sugestii acceptate/respinse, atingeri observate, efectul pe sesiune și mementouri rezolvate. Istoricul între călătorii cere o sursă separată. |

## Vizorul ocular și limitele datelor

Propunem o bandă panoramică pe ochi, luminanță ușor desaturată, contur fin al pleoapei și o etichetă pentru ochiul folosit. Preferăm un decupaj produs și adnotat direct pe același cadru de P1. O alternativă este o regiune normalizată, cu identificator de cadru și transformarea exactă până la imaginea afișată. MJPEG separat de WebSocket cere sincronizare explicită pentru un contur anatomic.

În codul existent, perception/driver_cam/eye_cnn.py conține eye_crop. perception/main.py publică fluxurile driver/passenger și câmpuri numerice. Zona privirii pornește ca unknown în implementarea inspectată. Până la acordul cu P1, modulul păstrează valorile valide și arată „Decupaj ocular indisponibil”. Dacă ochiul devine nesigur, conturul dispare și seria primește o întrerupere. Dacă se pierde camera, zona păstrează dimensiunea și afișează motivul disponibil. Cifrele lipsă primesc „—”. Niciun cadru nu trebuie salvat pentru acest vizor.

Observație de integrare: e2e_ms_p95 din procesul actual măsoară captura până la publicarea cadrului de către percepție. Eticheta pentru această sursă este „Captură → publicare”. Pentru o metrică până la UI este necesară o măsurătoare suplimentară.

## Pași după aprobare

1. Structură, bandă de performanță și camere. Verificare cu stare simulată, pierdere cameră și deconectare WebSocket independentă.
2. Stare, previzualizări și modul ocular pe câmpurile existente. Verificare cu privire necunoscută, ochi nesigur și decupaj absent. Adăugarea decupajului live depinde de interfața convenită cu P1.
3. Graficul stării și modulul de reacție. Verificare cu 120 de mostre, pauză în flux și referință personală încă absentă.
4. Cabină, sugestie live, jurnal, A/B și fișă. Verificare pe secvența mesaj amânat → citit → răspuns și pe alarmă în timp ce asistentul vorbește.
5. Repetiție pe laptop și proiector. Camera, alarma și performanța trebuie să poată fi identificate din fiecare secțiune. Harta și panoul regizorului au intrări proprii, în afara dashboard-ului.

Fiecare funcție verificată se poate livra printr-un commit uman separat pe p4-dashboard, în engleză și la imperativ, de exemplu `dashboard: add persistent camera view`.

## Moodboard și registru de integrare

[Moodboard interactiv](dashboard-moodboard.html) · [Schița de compoziție](drivemate-privire.html)

| Pas documentat | Decizie și motiv | Verificare pentru integrare |
|---|---|---|
| 1. Ierarhie | Performanța și camera au poziții stabile. Detaliile se deschid local. | La schimbarea modulului rămân vizibile camera și alerta. |
| 2. Limbaj vizual | Am stabilit paleta, fonturile, unitățile, spațierea și tratarea valorilor lipsă în moodboard. | Verificare la proiector, zoom 200% și navigare cu tastatura. |
| 3. Mișcare | Schimbarea fiabilității retrage conturul. Evenimentul visual_cue accentuează rama o singură dată. O reacție nouă mută marcajul față de referința fixă. | Tranziții de 160–240 ms, actualizare directă la reduced motion. Păstrăm cele trei serii de scoruri fără interpolare și alerta imediată. |
| 4. Date și proprietari | P1 furnizează imaginea și detecțiile, P2 publică starea, P3 gestionează vocea, P4 afișează și trimite comenzi. | Comparăm datele fiecărui modul cu producătorul, schema partajată și fixture-ul canonic când devin disponibile. |

### Modificări de interfață în așteptare

- **P1 ↔ P4, decupaj ocular.** Propunere de discutat cu P1: flux de decupaj adnotat în procesul de percepție, folosind geometria aceluiași cadru. Stabilim transportul și comportamentul când dispare fața. Consumatorul poate funcționa între timp cu MJPEG șofer și valorile numerice. Un flux video separat ar necesita documentarea endpointului, fără a introduce imagini în starea JSON.
- **P1 → P2 → P4, fiabilitate și privire.** Consumăm driver.eyes.reliable și driver.gaze.zone. Când zona primită este unknown, afișăm „Direcție nedeterminată”. Parametrii oculari propuși în P1 rămân opționali pentru UI.
- **P2/P3 → P4, reacție.** Poziția marcajului provine din driver.reaction și baseline_ms pentru același canal. Ultimul input vine din interaction.last_input. Starea absentă și referința zero dezactivează raportul. Schimbarea de animație este locală și nu adaugă câmpuri în contract.

La fiecare pas următor consemnăm funcția, producătorul, câmpul și unitatea, decizia vizuală, verificarea efectuată și rezultatul. Pentru o modificare de schemă urmăm §13 din plan: propunere CONTRACT pe grup, acord cu proprietarii, câmp opțional cu valoare implicită, versiune și fixture canonic actualizate împreună. Copia inspectată nu conține shared/contracts.py sau tests/core/fixtures/state_example.json. Exemplul P3 rămâne provizoriu.

## Baza implementată pe p4-dashboard

Deschide [dashboard/index.html](../../dashboard/index.html) într-un browser modern. Pagina pornește cu o sesiune simulată local. Selectorul Live deschide ws://localhost:8000/ws/ui și imaginea MJPEG de pe portul 8001. Camera pasagerului se încarcă la extinderea secțiunii. Un laptop diferit de cel care rulează serviciile necesită configurarea adreselor într-o etapă ulterioară.

| Pas | Rezultat | Verificare |
|---|---|---|
| 1. Structură și sursă | Bandă de performanță și cameră ancorate. Modul simulat generează mostre la 10 Hz și o ilustrație sintetică. | Deschidere directă în Edge, confirmare stare și valori populate. |
| 2. Stare și calitatea datelor | Citire a câmpului state din mesajul WS de tip state, risc, nivel, scoruri și ultimele 120 de mostre. La deconectare se golesc valorile. După două secunde fără stare nouă, UI marchează datele neactualizate. | Schimbare Simulat → Live cu stare parțială injectată în testul browserului. Valoarea zero se păstrează, câmpurile absente apar cu „—”. Reconectare și revenire la simulare verificate. |
| 3. Privire | PERCLOS, durată clipire, timp în afara drumului, EAR, ochiul ales și fiabilitate. Ilustrația apare în simulare. | Citirea valorilor din DOM în Edge. Așteptăm fluxul ocular de la P1 pentru decupajul real. |
| 4. Reacții | Timpul curent și referința în ms pentru trei canale. Marcajul animat reprezintă raportul pe scara 0–2×, cu referința la mijloc. | Valorile randate pentru reacție și poziția marcajului au fost inspectate în Edge. |
| 5. Integrare | Consumăm structura provizorie descrisă în §7 și fixture-ul P3. Nu se adaugă câmpuri la contract. | Sintaxa JavaScript verificată cu Node. Verificarea cap-coadă cu serviciile P1/P2 și proba pe proiector sunt restante. |

Fișierele bazei sunt dashboard/index.html, dashboard/src/monitor.css și dashboard/src/monitor.js. Modulul de voce P3, jurnalul, cabina extinsă și fișa călătoriei sunt etape ulterioare.

## Dashboard React · versiunea curentă

Din rădăcina proiectului: `cd dashboard`, apoi `npm ci` și `npm run dev`. Deschide URL-ul Vite afișat în terminal. Pentru repetiție, `npm run build` și `npm run preview` servesc versiunea compilată. Deschiderea directă a fișierului HTML se aplică doar prototipului anterior.

| Pas | Implementare și responsabilitate |
|---|---|
| Structură | React montează un ecran de monitorizare cu navigare internă. Camera și banda de performanță rămân ancorate. Harta, simulatorul și Contact rămân experiențe separate. |
| Sursă | session.js gestionează o sesiune WebSocket, reconectarea, întreruperile și istoricul de 120 de mostre. Simularea consumă exemplul P3, cu scoruri și semnale sintetice explicite. |
| Vizualizare | Canvas pentru portret și istoricul fără interpolare. CSS pentru marcajul reacției și filtrul decupajului. Conturul pentru visual_cue respectă setarea de mișcare redusă. |
| Secțiuni | General, privire, reacție, cabină/telefon, asistent/jurnal, A/B, fișa și telemetria. Detaliile se deschid local. Jurnalul reține cel mult 60 de evenimente în memorie. |
| Integrare | În Live, butonul de voce inițializează API-ul P3 pe același WebSocket. Proxy-ul Vite servește rutele /tts și /media de la core, iar clipurile locale vin din public/sounds. Tasta D cere comanda debug. Confirmarea formatului comenzii și a evenimentelor rămâne la integrarea cu P2. |
| Configurare | VITE_UI_WS și VITE_VIDEO_ORIGIN pot suprascrie adresele localhost. VITE_EYE_STREAM_URL este opțional, doar pentru un flux de decupaj furnizat de P1. Geometria adnotată aparține producătorului video. Niciun câmp nou obligatoriu în JSON. |
| Date încă de convenit | Comparația cu ultima călătorie, pauzele efectuate, mediile de reacție pe călătorie și latența până la randarea în UI au nevoie de măsurători agregate sau câmpuri convenite cu P2. Contoarele și ultima reacție afișate astăzi au semnificațiile din exemplul existent. |

Verificări efectuate: compilare Vite de producție și randare în Edge cu exemplul P3. Validarea fizică a camerelor și a vocii în Chrome, sincronizarea oculară și testul cu serviciile reale rămân pentru integrarea pe laptopul de demo.

## Revizie vizuală · cameră și instrumente

| Pas | Comportament |
|---|---|
| 1. Vizor rezervat camerei | Modul Simulat arată un cadru neutru și comanda „Treci în Live”. În Live, aceeași zonă păstrează proporțiile și găzduiește fluxul MJPEG sau starea de eroare cu reîncercare. Ideea modelului 3D a fost retrasă. |
| 2. Privire de ansamblu | Atenția folosește o scară semicirculară cu 32 de segmente și scorul numeric. Oboseala, dezinteresul și istoricul lor rămân alături. Datele lipsă apar cu „—”. |
| 3. Context și evenimente | Sub vizor apar viteza, durata și ETA din trip. Rezumatul afișează ultimele trei evenimente din jurnalul sesiunii, cu oră și sursă disponibilă. |
| 4. Ecrane înguste | Vizorul și cardurile curg într-o singură coloană. La scroll, vizorul devine compact și ascunde sumarul călătoriei. Tranzițiile pentru detaliile modulare respectă preferința de mișcare redusă. |

Interfețele P1–P3 rămân cele documentate pentru camera locală și starea primită prin WebSocket.

### Referințe de proiectare

- Direcție vizuală și ierarhie pentru instrumentar: [Frontend Design](https://agenticskills.io/skills/frontend-design) și [Refactoring UI](https://refactoringui.com/).
- Layout și comportament: [Learn Responsive Design](https://web.dev/learn/design/), [Motion pentru React](https://motion.dev/docs/react) și [Animations.dev](https://animations.dev/).
- Repere de compoziție pentru navigare și carduri: [Mobbin](https://mobbin.com/), [shadcn/ui Blocks](https://ui.shadcn.com/blocks) și [Godly](https://godly.design/). Land-book a răspuns cu HTTP 403 la consultare.
