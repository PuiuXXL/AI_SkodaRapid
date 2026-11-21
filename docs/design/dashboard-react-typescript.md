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

