# Obsidian Orange în DriveMate

Sistem vizual comun adoptat la 21 noiembrie 2026. Sursa completă este în [skill set](../../.agents/skills/obsidian-orange-web-skill/SKILL.md); [AGENTS.md](../../AGENTS.md) îl face regulă pentru modificările viitoare ale interfețelor.

## Direcție și ecrane

Referințele 01 și 08 stabilesc atmosfera grafit și ierarhia compactă. Referința 02 contribuie cu camera ca suprafață principală, 09 cu harta simulatorului, iar 10 cu organizarea telemetriei. Nu se introduc date, grafice sau destinații noi doar pentru asemănarea cu imaginile.

| Ecran | Scop și structură | Funcții de păstrat |
|---|---|---|
| Dashboard | Meniu lateral → performanță → cameră + stare generală → istoric, semnale și jurnal | Live/simulare, cameră mini, voce, detalii, navigare pe secțiuni |
| Simulator | Același meniu → hartă dominantă → opriri și controale → preview JSON | Puncte, reordonare, straturi, redare, pauză, resetare, export |
| Test voce P3 | O singură pagină cu panouri opace și comenzi lizibile | Microfon, TTS, evenimente, transcriere și jurnal; fără rute inventate |

Schiță: `[meniu flotant 268/80] [titlu + stare / telemetrie / cameră | scoruri / analiză]`; pe mobil: `[buton Meniu + DriveMate] [conținut într-o coloană]`, cu navigarea într-un sertar modal.

## Tokenuri și mișcare

Tokenurile comune sunt în `dashboard/src/voice/obsidian-tokens.css`, servit și de serverul de test vocal existent. Culori centrale: canvas `#090a0c`, panouri `#16181c`, suprafețe ridicate `#1c1f24`, text `#f4f2ef`, text secundar `#b2b0af`, accent `#ff7144`. Fontul existent Segoe UI rămâne; valorile folosesc cifre tabulare. Ritm de 8 px, ajustări de 4 px, carduri de 16 px. Roșul și galbenul păstrează semnificația alertelor.

| Declanșator | Scop / componentă | Implementare | Mișcare redusă |
|---|---|---|---|
| Extindere/restrângere | Continuitatea meniului și a spațiului de conținut | CSS, 220 ms ease-out; [tranziții CSS](https://developer.mozilla.org/en-US/docs/Web/CSS/transition) | Schimbare imediată |
| Navigare/secțiuni | Indicatorul urmează selecția reală | Motion existent, 220 ms fără bounce; [layout](https://motion.dev/docs/react-layout-animations) | Fără deplasare |
| Deschidere meniu mobil | Acces la navigare, focus și fundal modal | Dialog nativ; fără animație de intrare | Identic |
| Hover/focus | Feedback pe controale | CSS culoare/bordură, 140 ms | Imediat |

Nu se adaugă biblioteci. Intrarea decorativă GSAP este eliminată din monitorizarea operațională. Datele live și alarmele nu primesc animații decorative. Materialul translucid este rezervat meniului și panourilor flotante; telemetria, formularele și jurnalul rămân opace. Hărțile rutieră, satelit și relief păstrează informația cartografică originală.

## Verificare

- Build de producție și verificare TypeScript: reușite.
- Cele 8 teste existente pentru date, randare, scoruri și geometria traseului: reușite.
- Simulatorul a fost inspectat în Chrome la lățime desktop: suprafețe grafit, accent portocaliu, hartă, panouri flotante și navigare restrânsă vizibile.
- Verificarea interactivă desktop/mobil nu a putut fi finalizată: controlul ferestrei Chrome a fost întrerupt de inputul utilizatorului. Sertarul mobil, focusul, Escape și preferința meniului necesită o probă manuală în browser.
- Validatorul Python al skill-ului nu a rulat, deoarece Python nu este instalat în mediul disponibil. Pachetul sursă este păstrat în proiect și apare în catalogul de skill-uri al sesiunii.

Excepții deliberate: imaginile cartografice își păstrează semantica. Ilustrația oculară folosește iris arămiu cu fibre și reflexii, scleră grafit și tokenuri optice comune; nu reprezintă o măsurătoare live. Documentele istorice, schițele și moodboard-ul rămân referințe, nu ecrane de aplicație. Modulele de percepție, core și asistent nu sunt rescrise pentru o cerință vizuală.
