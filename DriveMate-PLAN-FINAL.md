clea# DriveMate: planul final de execuție, v2 (AI_SkodaRapid)

> Documentul unic după care lucrează echipa. Înlocuiește `DriveMate-PLAN-FINAL-v1.md`, `PROIECTARE-FINALA.md` și `rezumat-ai-drive-assistant.md`.
> „DriveMate” e nume de lucru.

---

## Ce s-a schimbat față de v1

1. **Două camere dedicate:** una strict pe șofer, una strict pe pasagerul din dreapta. Bancheta din spate nu mai are cameră.
2. **O inovație nouă din fuziunea celor două camere:** *distragerea provocată de pasager* (de exemplu, pasagerul îi arată ceva pe telefon).
3. **Telegram a fost scos.** Mesajele vin și pleacă **prin telefonul real al șoferului** (KDE Connect, Android), iar contactele și juriul au **o pagină web proprie**: DriveMate Contact.
4. **Mementouri pe traseu, legate de opriri** (stratul K): „amintește-mi la benzinărie să iau lichid de parbriz”.
5. **Recomandarea de muzică la dezinteres (D)** e acum obligatorie, iar efectul ei se măsoară.
6. **Măsurarea performanței e un strat separat (J):** sistemul, șoferul și asistentul.
7. **Responsabilitățile au fost reîmpărțite.** P4 avea prea mult de lucru.
8. **Corecturi:**
   - formularea despre confidențialitate e acum exactă;
   - am scos „video de rezervă” de duminică, pentru că contrazicea decizia de a nu înregistra video.

### v2.1 (ultimele modificări)
9. **Contactul de încredere.** Șoferul e obosit și refuză asistentul („lasă-mă în pace”). Atunci asistentul tace, iar o **regulă** îi trimite un SMS unei persoane configurate. Răspunsul acelei persoane îi e citit șoferului (C10, D10, F8, scena 6).
10. **Fișierele de rol** (`roluri/P1…P4`): ce face fiecare, în ce ordine și cum (secțiunile 10 și 13).
11. **Configurările sunt împărțite pe module** (`perception.yaml`, `thresholds.yaml`, `assistant.yaml`), iar dependențele pe roluri, în `requirements/`. Așa nu apar conflicte.

---

## 0. Ideea și pitch-ul

> **Un copilot care nu doar vede că ești distras, ci înțelege *de ce* (o cauză din cabină, oboseală sau dezinteres), rezolvă cauza, știe când să tacă, comunică cu tine în ambele sensuri (voce, gesturi, mișcări din cap), îți preia telefonul ca să nu-l mai atingi și măsoară dacă te-a ajutat.**
> Siguranța e deterministă. LLM-ul vorbește doar când regulile îi dau voie.

**Povestea:** ADDW (camera care urmărește șoferul) e obligatoriu în UE din 7 iulie 2026, dar doar pe mașinile **noi**. Un Skoda Rapid din 2014 nu îl are. DriveMate aduce siguranța din 2026 în orice mașină, cu **un laptop și două telefoane**. Problema pe care industria n-a rezolvat-o: șoferii opresc aceste sisteme din cauza alertelor false.

**Fraze pentru prezentare:**
- „Alte sisteme îți spun că ești distras. Al nostru rezolvă motivul.”
- „Primul asistent de atenție pe care nu vrei să-l oprești.”
- „Siguranța nu se oprește. Personalitatea se reglează.”
- „Zero atingeri ale telefonului.”

**Cele 3 inovații din pitch** (restul apar în demo, dar nu le numerotăm pe slide):
1. **Înțelege cauza distragerii și o rezolvă:** două camere, o singură concluzie. Exemple: pasagerul care îți arată ceva, mesajul de pe telefon, copilul din spate.
2. **Separă oboseala de dezinteres**, prin timpul de reacție măsurat pe 3 canale (privire, voce, gest) față de referința personală a șoferului. Fiecare primește alt remediu: pauză sau muzică.
3. **Dovada că nu enervează și nu depinde de AI:**
   - contorul live „prag simplu vs. DriveMate”;
   - oprirea LLM-ului în fața juriului, iar siguranța funcționează la fel.

**În afara scopului:** diagnostic medical, alcool, droguri. „Nu facem diagnostic medical, măsurăm atenția.”

---

## 1. Deciziile finale

| # | Decizie |
|---|---|
| 1 | **Două camere dedicate.** **Camera șofer** = webcam-ul laptopului, pe bord, doar pe șofer: ochi, privire, reacții, cap, gesturi, telefonul șoferului, identitate. **Camera pasager** = un telefon (DroidCam, **prin USB**), doar pe pasagerul din dreapta: identitate, treaz/adormit, dacă vorbește, telefonul pasagerului, gesturi. **Locul fiecărei persoane e dat de camera în care apare**, deci nu mai e nevoie de tracking între locuri. **Bancheta din spate n-are cameră.** Ocupanții din spate se declară vocal sau din panou. Dacă o cameră cade, cealaltă continuă, iar sistemul anunță. |
| 2 | **Telefonul șoferului e conectat** prin KDE Connect (Android). SMS-urile și WhatsApp-ul se citesc din notificări, iar răspunsul pleacă tot prin telefon. **iPhone nu e suportat**: iOS nu permite accesul la notificări. Telefonul folosit în demo e Android. |
| 3 | **Fără Telegram.** Contactul de urgență și juriul folosesc **DriveMate Contact**, pagina noastră web (QR), publicată cu un tunel `cloudflared`. |
| 4 | **Vocea în română**, prin Google Chrome, half-duplex (asistentul nu ascultă cât timp vorbește). Dacă testele din seara asta pică, trecem pe engleză. Slide-urile și README-ul sunt în engleză. |
| 5 | **Siguranța e locală și deterministă** (P0–P2). LLM-ul e doar pe calea lentă (P3–P4) și nu blochează niciodată nimic. |
| 6 | **Contractul JSON v2** e cel din secțiunea 7. Se închide **în noaptea asta, la 00:30**. |
| 7 | **Rezerva de demo:** redăm fluxul JSON al percepției, înregistrat pentru fiecare scenă. **Nu înregistrăm niciodată video.** |
| 8 | **Funcțiile M** sunt exact cele din scenariul final (secțiunea 9). Restul sunt S sau tăiate. |
| 9 | **Laptopul de demo** e cel mai puternic din echipă, ideal cu GPU NVIDIA. Toate măsurătorile se fac pe el. Dacă rulează Windows, puntea cu telefonul (KDE Connect) rulează pe un laptop cu Linux din echipă și trimite mesajele la core prin rețea. |
| 10 | **Contactul de încredere și contactul de urgență** sunt configurate în profil (implicit aceeași persoană), **cu acordul șoferului dat la configurare**. Numerele de telefon stau doar în `.env`, nu în repo. |
---

## 2. Principii de design

1. **Siguranța e deterministă.** Alarmele nu depind de LLM, de internet sau de vocea din cloud.
2. **Șoferului îi vorbim, nu-i arătăm.** Șoferul primește doar voce și un semnal luminos. Dashboard-ul e pentru pasager și juriu.
3. **Șoferul nu atinge telefonul.** Orice face telefonul se poate face prin voce, cap sau gest.
4. **Fiecare alertă are o explicație** („ai privit în jos 2,1 s la 110 km/h”).
5. **Fiecare decizie are o sursă vizibilă:** `REGULĂ` sau `LLM`.
6. **Măsurăm tot:** sistemul, șoferul și asistentul (stratul J).
7. **Sistemul anunță când nu mai poate proteja** („Nu te mai văd”) și nu tace niciodată fără să spună.
8. **Ce nu apare în scenariul de demo nu se construiește.**
9. **Nimic pe ascuns.** Când anunță pe cineva despre șofer, asistentul îi spune și șoferului.

---

## 3. Arhitectura

```
 Cameră ȘOFER          Cameră PASAGER            Microfon     Simulator + panou regizor
 (webcam laptop)       (telefon, DroidCam USB)       │        (traseu, viteză, POI, opriri)
        │                      │                     │                   │
        ▼                      ▼                     ▼                   │
 ┌──────────────────────────────────────────────────────────┐            │
 │ A. PERCEPȚIE   A-Ș (șofer)  ·  A-P (pasager)  ·  audio    │ P1         │
 └───────────────────────────┬──────────────────────────────┘            │
                             ▼  WS /ws/perception ~15 Hz                 ▼
 ┌────────────────────────────────────────────────────────────────────────────────────┐
 │ B. MOTOR DE CONTEXT (determinist) → stare JSON ~10 Hz                core :8000, P2  │
 │    reacții · F · D · atenție · risc · CAUZĂ (fuziune 2 camere) · A/B · mementouri   │
 └──────────────┬──────────────────────────────────────────────────┬──────────────────┘
                ▼                                                  ▼
 ┌──────────────────────────────┐                ┌──────────────────────────────────┐
 │ C. SIGURANȚĂ (P0–P2)         │───── veto ────▶│ D. COPILOT LLM (P3–P4)            │
 │ alarme locale, SOS,          │                │ doar acțiuni din listă,           │
 │ „Nu te mai văd”              │                │ validate de C                      │
 └──────────────┬───────────────┘                └──────────────────┬───────────────┘
                └───────────────────┬───────────────────────────────┘
                                    ▼
                     ┌───────────────────────────────┐
                     │ ARBITRU (P0 > P1 > … > P4)    │
                     └───┬──────────────┬────────────┘
                         ▼              ▼
   E. INTERACȚIUNE (voce ↔, gesturi, cap)   F. MESAJE: telefonul șoferului (KDE Connect ↔)
                         │                     · DriveMate Contact (web ↔) · Twilio (apel SOS)
                         ▼
   H. DASHBOARD · J. PERFORMANȚĂ · K. MEMENTOURI · I. HARTĂ + REGIZOR + REDARE JSON
```

**Cele două căi:**
```
CALEA RAPIDĂ (siguranță): cameră → percepție → reguli → WS → clip audio local      țintă < 300 ms, fără rețea
CALEA LENTĂ (LLM):        eveniment → rezumatul stării → LLM (streaming) → validare → voce
                          timeout 2,5 s → text fix · cel mult o intervenție proactivă la 30 s · veto la P0–P2
```

| Modul | Responsabil | Intrare | Ieșire |
|---|---|---|---|
| A. Percepție (2 camere + audio) | P1 | cadre, audio | `driver.*`, `passenger.*`, `perf.cameras` |
| B. Context + cauza din 2 camere | P2 | A + simulator | `assessment`, `cause`, `ab`, `intervention`, `blind_m` |
| C. Siguranță + arbitru + SOS + Twilio + contactul de încredere | P2 | starea completă | `safety`, alarme, apel, SMS către contact |
| D. Copilot LLM + muzică | P3 | stare + memorie scurtă | acțiuni JSON |
| E. Interacțiune + clipuri audio | P3 (P1 pentru gesturi și cap) | voce, gesturi, cap | `interaction` |
| F. Puntea cu telefonul | P3 | notificări Android | `phone`, `messages` |
| F. Regula de timing a mesajelor | P2 | `messages`, `safety` | amână / întreabă / citește |
| F. DriveMate Contact + tunel | P4 | WS | pagina web |
| H, I, J (UI). Dashboard, simulator, regizor, redare, performanță | P4 | WS | UI |
| K. Mementouri | P3 (înțelegerea cererii) + P2 (declanșarea) + P4 (POI pe hartă) | voce, simulator | `reminders` |

**Backend:** Python 3.11, FastAPI, WebSocket, Pydantic v2, orjson, `dbus-next` (KDE Connect). **Frontend:** web în Google Chrome (dashboard + voce), Leaflet pentru hartă. **Configurare (fiecare modul are fișierul lui):** `perception/config/perception.yaml` (P1), `core/config/thresholds.yaml` + `core/config/templates.yaml` (P2), `assistant/config/assistant.yaml` + `assistant/data/media_catalog.json` (P3), `profiles/<nume>/profile.json` + `simulator/stops.json` (P4), `.env` (chei și numere de telefon).

**Confidențialitate (formularea exactă pentru slide):**
- Imaginile nu pleacă niciodată de pe laptop și nu se înregistrează.
- În cloud ajung doar:
  - starea JSON rezumată și textul conversației și al mesajelor, la LLM;
  - vocea, la recunoașterea vocală din Chrome;
  - raportul SOS, la Twilio.
- Embedding-urile faciale rămân pe laptop.
- Din telefon citim doar notificările aplicațiilor din lista albă (SMS, WhatsApp).

---

## 4. Funcțiile, pe straturi

**M** = obligatoriu (apare în scenariul final) · **S** = doar după ce merge tot M · **X** = tăiat.

### A. Percepție, P1

#### A-Ș: camera șoferului (webcam-ul laptopului)

| ID | Funcție | Cum | Prio |
|---|---|---|---|
| AS1 | Repere faciale + blendshapes | MediaPipe Face Landmarker pe **decupajul feței** (478 de repere, 52 de blendshapes, matricea capului) | M |
| AS2 | Ochi: EAR, clipit, durata clipitului, PERCLOS pe 60 s, microsomn | EAR **pe fiecare ochi** (contează cel mai bine văzut) + `eyeBlinkLeft/Right` | M |
| AS3 | Căscat | `jawOpen` peste prag ≥ 2 s | M |
| AS4 | Poziția capului + căderea de oboseală | matricea capului: cădere lentă de pitch, cu ochii care se închid | M |
| AS5 | ★ Zone de privire calibrate per șofer | kNN pe (unghiurile capului + iris), cu calibrarea salvată în profil. Zonele: drum, oglinzi, bord, ecran, poală, **pasager** | M |
| AS6 | ★ VATS + entropia privirii | priviri scurte pe 60 s + entropia distribuției pe zone | M |
| AS7 | ★ Telefonul șoferului | YOLO26n (clasa 67) pe zona mâinilor, combinat cu geometria (încheietura lângă față). **Tiparul „poală”:** priviri repetate spre `lap` (≥3 în 20 s sau una >2 s) când mâinile nu se văd → `phone.source = "lap_pattern"`, cu încredere mai mică | M |
| AS8 | ★ Răspuns din cap | da = oscilație de pitch, nu = oscilație de yaw: ≥2 schimbări de sens în <1,2 s, ochi deschiși, **doar în fereastra de dialog** | M |
| AS9 | Gesturi 👍 👎 ✋ | MediaPipe Gesture Recognizer, doar în fereastra de dialog sau cu mâna ridicată | M |
| AS10 | Identitate | OpenCV YuNet + SFace, la apariția feței, reverificare la ~10 s | M |
| AS11 | Vorbește | oscilația `jawOpen` | M |
| AS12 | Cameră acoperită / față pierdută | `monitoring_ok=false` → regula C7 | M |
| AS13 | Privire spre spate | fața se pierde după un yaw mare care creștea spre dreapta → `rear_seat` pentru maximum 3 s (YOLO26n-pose la frecvență mică, ca a doua confirmare) | S |
| AS14 | Ochi nesiguri (ochelari de soare) | `eyes.reliable=false` → doar metrici de cap | S |

#### A-P: camera pasagerului (telefon, DroidCam prin USB)

| ID | Funcție | Cum | Prio |
|---|---|---|---|
| AP1 | Prezență + identitate | YuNet + SFace; locul = `front_right` (camera) | M |
| AP2 | Treaz / adormit | ochi închiși > 10 s + capul lăsat → `awake=false` | M |
| AP3 | Vorbește | oscilația `jawOpen` | M |
| AP4 | Telefonul pasagerului | YOLO26n (clasa 67) + încheietura din YOLO26n-pose | M |
| AP5 | Cameră acoperită / pasager absent | `passenger.present=false`, anunțat | M |
| AP6 | Gesturi ale pasagerului (👍 la o delegare) | Gesture Recognizer în fereastra adresată pasagerului | S |

**Filtrare în timp (obligatorie):** EMA, histerezis, durată minimă pentru fiecare eveniment. Încredere mică → `unknown` și fără alertă.

### B. Înțelegerea stării (determinist), P2

| ID | Funcție | Cum | Prio |
|---|---|---|---|
| B1 | ★ Reacția pe 3 canale | **Vizuală:** de la semnalul discret până când privirea revine pe drum. **Verbală:** de la sfârșitul întrebării până la începutul vorbirii (WebAudio). **Gest:** de la propunere până la 👍/👎/mișcarea capului. Referința = mediana primelor 3–5 reacții. `r = latență / referință`. Lipsa răspunsului = valoarea maximă | M |
| B2 | ★ Oboseala F vs. dezinteresul D | formulele de mai jos. **D contează doar când F e mic și contextul e monoton:** în trafic solicitant entropia scade și ea (Victor et al., 2005) | M |
| B3 | Atenție + risc 0–3 | atenția din timpul cu privirea pe drum (fereastră de 10 s), VATS, telefon. Riscul combină atenția, F și viteza (în parcare 0, la 130 km/h maxim) | M |
| B4 | ★ **Cauza distragerii, din 2 camere** | zona privirii (camera șofer) + ce face persoana de acolo (camera pasager) + contextul → `cause.label`: `passenger_showing_phone` (privire spre pasager ≥3 ori în 30 s **și** pasagerul ține telefonul), `passenger_talk`, `incoming_message`, `phone`, `child_activity` (spate, declarat) | M |
| B6 | Metri orbi | viteza × timpul cu privirea în afara drumului, pe segmentul de traseu | M |
| B7 | Context simulat | viteză, drum, poziție, ETA, durata drumului, POI-uri, oprire | M |
| B8 | ★ Prag simplu în paralel | același detector, prag fix, fără zone, calibrare sau context → `ab.naive_alerts` vs `ab.our_alerts` | M |
| B9 | ★ Conversație în mașină | **buzele din ambele camere alternează** + nivelul microfonului → `conversation=true` (mai sigur decât doar microfonul) | M |
| B5 | Sondare rară | întrebare doar când F sau D sunt ambigue (0,4–0,6), maximum una la 10 minute | S |

```
F = 0.30·PERCLOS + 0.20·durata_clipitului + 0.15·căscat + 0.20·reacție_lentă + 0.10·nodding + 0.05·durata_drumului
D = 0.30·reacție_lentă + 0.25·(1 − entropia_privirii) + 0.20·rată_de_răspuns_scăzută + 0.15·răspunsuri_scurte + 0.10·monotonie
```
Toți termenii sunt normalizați între 0 și 1. Ponderile sunt în `thresholds.yaml`.

**Remedii:**
- **F (oboseală):** întrebarea KSS, apoi o pauză concretă. Dacă există un memento deschis, oprirea aleasă îl rezolvă și pe el.
- **D (dezinteres):** **muzică recomandată**. Dacă șoferul refuză: quiz sau podcast.

### C. Siguranță (reguli, fără LLM), P2

| ID | Funcție | Prio |
|---|---|---|
| C1 | Prioritățile P0–P4 + arbitrul: un nivel mai sus întrerupe instant tot ce e sub el (inclusiv muzica) | M |
| C2 | Escaladare: semnal discret (lumină sau ecran) → voce → alarmă | M |
| C3 | ★ Alarma cu numele șoferului („ANDREI!”): clip local pregenerat, sub 300 ms de la detecție până la sunet | M |
| C4 | Microsomn → alarmă → „Ești bine?” → anulare prin „da”, dat din cap sau 👍 | M |
| C5 | ★ Șoferul nu răspunde → numărătoare inversă → **instrucțiuni fixe pentru pasager, pe nume** (avariile, „rămâi pe linie”, niciodată „apucă volanul”) → fluxul SOS (F6) | M |
| C6 | ★ Butonul care oprește LLM-ul (din panoul regizorului): siguranța funcționează identic | M |
| C7 | „Nu te mai văd, monitorizarea e întreruptă” când camera șoferului e acoperită sau fața se pierde fără explicație | M |
| C8 | Veto: LLM-ul tace la P0–P2. 👎 reglează doar pragurile pentru P3–P4, în limite fixe. Microsomnul și șoferul care nu răspunde nu se reglează niciodată | M |
| C9 | Rezerve: LLM-ul nu răspunde în 2,5 s → text fix. Vocea din cloud cade → voce locală. Twilio cade → SMS de pe telefon + pagina Contact | M |
| C10 | ★ **Contactul de încredere.** Se declanșează când oboseala F e peste `safe_contact.fatigue_min` **și** șoferul refuză asistentul (D10). Regula: (1) **pune asistentul pe liniște** pentru `refusal_mute_min`: P3–P4 tac, P0–P2 rămân active; (2) dacă profilul are un contact de încredere și acordul șoferului, trimite **un SMS de pe telefonul șoferului** (șablonul de mai jos) și o **notificare galbenă** pe DriveMate Contact; (3) trimite cel mult un mesaj la `safe_contact.cooldown_min`. Răspunsul contactului intră în coada de mesaje și e livrat după regula F2. **LLM-ul nu poate declanșa și nici bloca acest mesaj** | M |

**Raportul SOS (șablon fix, fără LLM):**
„Alertă automată DriveMate. {nume} nu răspunde de {s} secunde. Ocupanți: {n}; pasagerul din dreapta e {treaz/adormit/absent}. Locație: {link Google Maps}. Ora: {hh:mm}.”

**Mesajul către contactul de încredere (șablon fix, fără LLM, în `core/config/templates.yaml`):**
„DriveMate: {nume} pare obosit ({durată} la volan) și nu vrea pauză acum. Scrie-i un mesaj (i-l citesc cu voce tare) sau sună-l. Locație: {link Google Maps}. Ajunge în ~{eta} min.”

**Fluxul complet:**
```
F peste prag → asistentul pornește o conversație ca să-l țină treaz pe șofer (inclusiv întrebarea KSS)
  → șoferul refuză: „lasă-mă în pace” / „taci” / „nu acum” / ✋ / 👎
  → clip: „Ok, te las în pace.”  (+ „Îi dau de veste lui {contact}.” când announce = true, implicit)
  → REGULA C10: asistentul tace (doar P3–P4) + SMS de pe telefonul șoferului + notificare galbenă pe pagina Contact
  → contactul răspunde (WhatsApp / SMS / pagina) → regula F2 → mesajul e citit
  → asistentul poate propune O SINGURĂ DATĂ o oprire („Oprim la OMV peste 12 km?”)
  → dacă oboseala se agravează: alarmele P1 și SOS-ul P0 funcționează normal, liniștea nu le afectează
```

### D. Copilotul (LLM), P3

| ID | Funcție | Prio |
|---|---|---|
| D1 | Primește un rezumat scurt al stării și o memorie scurtă. Întoarce **doar** acțiuni din listă (secțiunea 6), validate de C. Timeout 2,5 s, streaming | M |
| D2 | ★ Rezolvarea cauzei. **Pasagerul arată telefonul:** „Maria, poți să-i povestești tu? Andrei, ochii pe drum.” **Telefonul șoferului:** „Lasă telefonul, ți-l citesc eu.” **Copilul din spate:** ghicitoare pentru copil (S). Dacă remediul nu scade privirile în fereastra configurată, se renunță la el | M |
| D3 | ★ Remediul pentru F: „Cât de obosit ești, 1–9?” (KSS) → pauză concretă. **Oprirea o alege regula** (cea mai apropiată care rezolvă și un memento deschis), iar LLM-ul doar o formulează | M |
| D4 | ★ Vorbire care cedează drumul: vocea e generată propoziție cu propoziție. La oglindă, manevră sau alertă se oprește în mijlocul frazei și reia cu „...cum ziceam” | M |
| D5 | Explicarea fiecărei alerte în jurnal și vocal, într-o frază | M |
| D6 | ★ Eficiența intervenției: atenția (și D sau F) înainte vs. după, cu ferestre configurabile (scurte în modul demo). Pe slide: „efectul măsurat în această sesiune” | M |
| D8 | ★ **Muzică recomandată la dezinteres:** LLM-ul alege din `media_catalog.json` după gusturile din profil, energia potrivită (pentru D: energie mare), ora și cabină (pasager adormit → volum mic; copil → doar `kid_safe`). Întreabă („Pare monoton. Pun ceva mai energic, din ce-ți place?”) → confirmare → redare. Efectul se măsoară (D6). Refuz → quiz sau podcast | M |
| D9 | ★ Înțelegerea mementourilor (K1): fraza liberă devine `create_reminder` cu o categorie validă | M |
| D10 | ★ **Conversația anti-oboseală și refuzul.** Când F trece de prag, asistentul pornește o conversație scurtă ca să-l țină treaz pe șofer (inclusiv întrebarea KSS). **Refuzul** e recunoscut întâi prin cuvinte-cheie (`assistant/refusal.py`, rapid și determinist: „lasă-mă în pace”, „taci”, „nu acum”, „nu vreau”), prin ✋ / 👎 în dialogul de oboseală și, ca rezervă, de LLM (`stay_silent` cu `reason="driver_refused"`). Rezultatul e evenimentul `driver_refused`, urmat de clipul **„Ok, te las în pace.”** Dacă se anunță contactul, **decide regula C10, nu LLM-ul** | M |
| D5b | Răspuns la „De ce m-ai atenționat?” | S |

**Regula de formă:** maximum ~15 cuvinte către șofer, nimic de citit, nimic în timpul manevrelor. Muzica scade automat cât vorbește asistentul.

### E. Interacțiune bidirecțională, P3 (+P1)

| ID | Funcție | Cum | Prio |
|---|---|---|---|
| E1 | Voce în ambele sensuri | STT: Web Speech API în **Google Chrome** (nu Chromium), recunoaștere continuă cu repornire în `onend`, numele asistentului căutat în text. TTS: edge-tts (voce românească), cu `speechSynthesis` ca rezervă. **Fereastră de dialog de 6 s** după fiecare întrebare | M |
| E3 | ★ Fuziune multimodală. **Da** = „da” / dat din cap / 👍. **Nu** = „nu” / clătinat / 👎. **Liniște** = ✋. **Refuz** (în dialogul de oboseală) = „lasă-mă în pace” / „taci” / ✋ / 👎. Jurnalul arată canalul | M |
| E5 | Cererile libere devin acțiuni din listă (muzică, mesaj, memento, oprire, preferințe) | M |
| E6 | **Half-duplex:** recunoașterea vocală se oprește cât vorbește asistentul (anularea ecoului din `getUserMedia` nu se aplică la Web Speech API) | M |
| E7 | Clipurile pregenerate: alarma cu numele fiecărui profil, „Ești bine?”, instrucțiunile pentru pasager, confirmările scurte | M |
| E4 | Cine vorbește = camera în care se mișcă buzele, plus permisiuni pe persoană | S |
| E2 | Barge-in: un flux WebAudio separat detectează vorbirea și oprește vocea asistentului | S |

| Cine | Poate | Nu poate |
|---|---|---|
| Șofer | confort, mesaje, mementouri, opriri, preferințe | să oprească siguranța |
| Pasager adult | media, delegări, propriile cereri | să schimbe setările șoferului, să-i citească mesajele |
| Copil (declarat) | media `kid_safe`, povești, ghicitori | mesaje, setări |

### F. Mesaje și telefon

| ID | Funcție | Cine | Prio |
|---|---|---|---|
| F1 | ★ **Puntea cu telefonul șoferului (KDE Connect, Android).** Laptopul și telefonul sunt împerecheate. `integrations/phone_bridge.py` ascultă pe D-Bus notificările noi, filtrează pe lista albă (SMS, WhatsApp) și pe contacte, apoi trimite la core: `{app, from, text, replyable}` | P3 | M |
| F2 | Regula de timing (REGULĂ): risc mare, viteză mare sau distragere → amână („Ți-l citesc imediat ce e liniște”). Pasageri prezenți → întreabă („Mesaj personal de la Mihai. Îl citesc tare?”). Altfel → citește | P2 | M |
| F3 | ★ **Răspuns fără atingere, trimis prin telefon.** Dictare → LLM-ul reformulează scurt și adaugă ETA → confirmare (👍 / dat din cap / „da”) → trimis. **WhatsApp:** prin acțiunea de răspuns a notificării (`sendReply`). **SMS:** `kdeconnect-cli --send-sms`. Contorul „atingeri telefon: 0” | P3 | M |
| F5 | ★ **DriveMate Contact** (înlocuiește Telegram): o pagină web servită de core, publicată cu `cloudflared tunnel --url http://localhost:8000` (fără cont), cu token aleator în link și QR. Contactul vede **starea șoferului** („Andrei conduce · ajunge în ~20 min · îți răspunde vocal”), poate trimite mesaje (intră în aceeași coadă) și primește **alerta SOS cu harta live** | P4 | M |
| F6 | ★ **SOS pe trei canale.** Apel Twilio cu raportul citit (TwiML `<Say>`, în română) + **SMS de pe telefonul șoferului** (KDE Connect) cu linkul Google Maps + alertă roșie pe DriveMate Contact, cu poziția live | P2 (logica + Twilio), P3 (SMS), P4 (pagina) | M |
| F8 | ★ **Mesajul către contactul de încredere** (C10): SMS de pe telefonul șoferului (`kdeconnect-cli --send-sms`; WhatsApp nu poate începe o conversație nouă din notificări) + notificare galbenă pe DriveMate Contact, cu câmpul „Scrie-i lui {nume}”. **Răspunsul contactului** (WhatsApp, SMS sau din pagină) îi e citit șoferului. După el, asistentul poate propune o singură dată o oprire | P2 (regula), P3 (SMS, citire), P4 (pagina) | M |
| F4 | Apel primit (pluginul de telefonie KDE Connect) → „Te sună Mihai. Îi trimit că revii după ce oprești?” → SMS automat | P3 | S |
| F7 | Juriul scrie live din DriveMate Contact (QR pe slide) | P4 | S |

**Condiții pentru F1/F3** (de testat în seara asta):
- Telefon **Android** cu aplicația KDE Connect și accesul la notificări permis.
- Pe laptop: KDE Connect (Fedora: `sudo dnf install kde-connect`), cu firewall-ul deschis (`sudo firewall-cmd --add-service=kdeconnect`).
- Laptopul și telefonul **în aceeași rețea**. WiFi-ul din sală poate izola dispozitivele, așa că folosiți hotspot-ul telefonului șoferului sau tethering prin USB.

### G. Cabina socială, P2

| ID | Funcție | Prio |
|---|---|---|
| G1 | Ocupanți: șofer (camera șofer), dreapta (camera pasager), spate (declarat). Profil, treaz/adormit, dacă vorbește | M |
| G2 | Conversație (B9) → `stay_silent` (vizibil în jurnal), **cu excepția situațiilor de siguranță sau cauză (P2/P3)** | M |
| G3 | Pasager adormit → volum mic, mesaje doar pe ecran. Șoferul rămâne fără stimulare, deci sondarea începe mai devreme | M |
| G5 | Telefonul în mâna pasagerului → **fără alertă** pentru șofer (pragul simplu ar fi dat alertă, deci contorul A/B crește) | M |
| G4 | Copil declarat → filtru `kid_safe` | S |
| G6 | Copil uitat în mașină | X |

### H. Dashboard și debug, P4

| ID | Funcție | Prio |
|---|---|---|
| H1 | Video din ambele camere cu detecțiile + **modul debug (tasta D)**: repere, raza privirii, eticheta zonei, EAR live, încheieturi, telefon, fps | M |
| H2 | Grafic cu **3 linii**: atenție, oboseală, dezinteres | M |
| H3 | Jurnal de evenimente: sursa (REGULĂ/LLM), explicația, canalul de input, latența | M |
| H4 | ★ Contorul: „prag simplu: N · DriveMate: M” | M |
| H6 | Hartă: traseul, POI-urile, mementourile, metrii orbi (în roșu), poziția la SOS | M |
| H7 | Ocupanți, cine vorbește, ce se redă, mesaje în așteptare, mementouri active, starea telefonului | M |

### I. Simulator, panoul regizorului, redare, P4

| ID | Funcție | Prio |
|---|---|---|
| I1 | Traseu oraș → autostradă: poziție, viteză, drum, ETA, **POI-uri cu categorii** (`stops.json`: fuel, cafe, pharmacy, supermarket, auto_parts) | M |
| I2 | Panou regizor: pornire/pauză, salt la scenă, accelerarea timpului, slider de viteză, **oprire la următorul POI**, **oprirea LLM-ului**, declararea ocupanților din spate, mesaj simulat, resetare | M |
| I3 | **Redarea fluxului JSON** înregistrat pe fiecare scenă (rezervă dacă CV-ul cedează live; restul rulează real) | M |

### J. Măsurarea performanței (nou ca strat separat), P1 + P2 + P4

| ID | Ce | Detaliu | Prio |
|---|---|---|---|
| J1 | ★ **Performanța sistemului** (panou vizibil tot demo-ul) | fps captură/procesare pe cameră · ms pe model (p50/p95): fața șoferului, fața pasagerului, pose, telefon, gesturi, SFace · latența cap-coadă (de la cadru la UI) · **latența alarmei** · LLM: primul token și total · STT: până la textul final · TTS: până la primul sunet · **mesaj primit → citit cu voce** · CPU, RAM, GPU, cadre aruncate | M |
| J2 | ★ **Performanța șoferului** (fișa călătoriei, pozitivă) | cel mai lung interval concentrat · reacția medie vs. referință, pe fiecare canal · metri orbi (azi vs. ultima călătorie) · evoluția atenției, F și D · pauzele făcute | M |
| J3 | ★ **Performanța asistentului** | alerte DriveMate vs. prag simplu (A/B) · efectul fiecărui tip de intervenție (+X%) · sugestii acceptate/respinse · mesaje gestionate fără mâini · **atingeri ale telefonului: 0** · mementouri rezolvate | M |
| J4 | **Benchmark pentru slide** | `scripts/benchmark.py`: fiecare model pe N cadre, pe laptopul de demo → tabel + grafic | M (prezentare) |
| J5 | Jurnalul sesiunii | JSONL cu toate stările și evenimentele → grafice pentru prezentare (A/B, latențe) | S |

**Implementare:** fiecare etapă pune un timestamp în `perf` (`time.perf_counter()`), `deque(maxlen=120)` pentru p50/p95, `psutil` pentru CPU/RAM, `pynvml` pentru GPU (dacă există).

### K. Mementouri pe traseu (nou), P3 + P2 + P4

| ID | Funcție | Cum | Prio |
|---|---|---|---|
| K1 | ★ Memento prin voce, cu confirmare | „Amintește-mi să iau lichid de parbriz când oprim la o benzinărie.” → LLM: `create_reminder {task: "lichid de parbriz", trigger: {type: "stop_at_category", category: "fuel"}}` → validare (categoria trebuie să existe) → „Notat: lichid de parbriz, la prima benzinărie. Bine?” → da / dat din cap / 👍 → activ | M |
| K2 | ★ Declanșare la oprire (REGULĂ) | viteza = 0 la un POI din aceeași categorie → **șablon fix**: „Ai zis să iei lichid de parbriz.” → 👍 = bifat · 👎 = păstrat pentru următoarea oprire. Se livrează **doar cu mașina oprită** (zero distragere) | M |
| K3 | ★ Legătura cu oboseala | când trebuie propusă o pauză (F), regula alege oprirea care rezolvă și un memento deschis: „Ai nevoie de pauză. Oprim la OMV peste 12 km, iei și lichidul de parbriz.” | M |
| K4 | Propunere la apropiere | POI din categoria unui memento la <1 km și risc ≤1 → „La 800 m e o benzinărie. Oprim pentru lichidul de parbriz?” | S |
| K5 | Alte declanșatoare | `arrive_destination`, `any_stop` | S |

---

## 5. Siguranța: prioritățile și regulile fixe

| Nivel | Ce | Cine decide |
|---|---|---|
| P0 | Șoferul nu răspunde → instrucțiuni pentru pasager, SOS pe trei canale | Regulă |
| P1 | Microsomn sau ochi închiși → alarmă | Regulă |
| P2 | Distragere critică: telefon, privire lungă în afara drumului la viteză mare | Regulă |
| P3 | Rezolvarea cauzei, mesaje, remediile pentru F și D | LLM, cu acordul regulilor |
| P4 | Confort: muzică, mementouri, conversație | LLM (mementourile la oprire: șablon) |

1. Alarmele sunt locale și instantanee (sub 300 ms).
2. Orice sunet care nu e critic se oprește la o alertă.
3. Șoferul nu primește niciodată ceva de citit și nu trebuie să atingă telefonul.
4. LLM-ul nu poate anula sau amâna o alertă și nu vorbește în timpul manevrelor.
5. Siguranța nu se poate opri.
6. Sistemul anunță când nu mai vede șoferul.
7. Fiecare componentă are o variantă de rezervă (C9).
8. „Lasă-mă în pace” oprește doar inițiativele asistentului (P3–P4), pentru un timp limitat. Alarmele, SOS-ul și livrarea mesajelor de la contacte funcționează în continuare.

---

## 6. LLM: acțiunile permise

| Acțiune | Parametri | Permisă la | Cere confirmare |
|---|---|---|---|
| `speak` | `to`, `text` (≤15 cuvinte pentru șofer) | P3, P4 | — |
| `ask` | `to`, `question`, `expects`: `yes_no` / `kss` / `free` | P3, P4 | — |
| `suggest_media` | `track_id` (din catalog, filtrat pe profil și cabină), `reason` | P4 | **da** |
| `play_media` / `stop_media` | `track_id` | P4 (oprirea: oricând) | — |
| `read_message` | `msg_id` | P3, P4 + regula F2 | da, dacă sunt pasageri |
| `reply_message` | `msg_id`, `text` (trimis prin telefon) | P3, P4 | **da** |
| `create_reminder` | `task`, `trigger {type, category}` | P3, P4 | **da** |
| `complete_reminder` | `reminder_id` | oricând | da |
| `suggest_stop` | `poi_id` (dintre cele propuse de regulă) | P3, P4 | da |
| `delegate` | `to_person`, `task` | P3 | — |
| `show_on_screen` | `text`, `target=passenger` | oricând | — |
| `set_preference` | `key`, `value` în limite | P4 | da |
| `stay_silent` | `reason` | oricând | — |

Orice altceva primit de la LLM e respins și trecut în jurnal. Maximum 3 acțiuni per răspuns.

---

## 7. Contractul JSON al stării (v2, se închide în noaptea asta la 00:30)

Zone de privire: `road`, `mirror_left`, `mirror_right`, `mirror_rear`, `cluster`, `infotainment`, `lap`, `passenger`, `rear_seat`, `away`, `unknown`. Zona `unknown` nu declanșează niciodată alertă.

```json
{
  "ts": 1763672400.123, "seq": 18231,
  "trip": { "speed_kmh": 118, "road": "highway", "elapsed_min": 74,
            "pos": { "lat": 45.75, "lon": 21.23 }, "eta_min": 20, "scene": 6,
            "stopped": false, "at_poi": null,
            "next_poi": { "id": "omv_km42", "category": "fuel", "dist_km": 12 } },
  "occupants": [
    { "id": 1, "seat": "driver",      "source": "cam_driver",    "profile": "andrei", "role": "adult" },
    { "id": 2, "seat": "front_right", "source": "cam_passenger", "profile": "maria",  "role": "adult" },
    { "id": 3, "seat": "rear",        "source": "declared",      "profile": "ioana",  "role": "child" }
  ],
  "driver": {
    "eyes":  { "ear": 0.27, "eye_used": "left", "perclos_60s": 0.08, "blink_ms": 180, "microsleep": false, "reliable": true },
    "head":  { "yaw": -4, "pitch": 2, "roll": 1, "nodding": false, "answer": null },
    "gaze":  { "zone": "road", "conf": 0.91, "source": "face", "off_road_ms": 0, "vats_60s": 2, "entropy_60s": 1.42 },
    "yawn": false,
    "speaking": false,
    "phone": { "in_use": false, "conf": 0.12, "source": null },
    "gesture": null,
    "reaction": {
      "visual_ms": 650, "verbal_ms": 1400, "gesture_ms": 900,
      "baseline_ms": { "visual": 500, "verbal": 900, "gesture": 800 },
      "missed": 0, "response_rate_10min": 0.8
    }
  },
  "passenger": { "present": true, "awake": true, "eyes_closed_s": 0, "speaking": false,
                 "holding_phone": true, "gesture": null, "answer": null },
  "conversation": false,
  "cause":      { "target": "passenger", "person_id": 2, "label": "passenger_showing_phone",
                  "glances_30s": 3, "conf": 0.8, "sources": ["cam_driver", "cam_passenger"] },
  "assessment": { "attention": 0.82, "fatigue": 0.35, "disengagement": 0.61, "risk": 1 },
  "safety":     { "level": "P3", "alert": null, "llm_allowed": true, "llm_enabled": true,
                  "monitoring_ok": true, "alarm_ms_last": 120 },
  "interaction": { "state": "speaking", "addressed_to": 1, "dialog_window_open": false,
                   "last_input": { "from": 1, "channel": "nod", "value": "yes", "ts": 1763672398.4 } },
  "assistant":  { "muted_until": null, "mute_reason": null },
  "safe_contact": { "name": "Mihai", "configured": true, "consent": true, "announce": true,
                    "notified_ts": null, "last_reply_msg_id": null },
  "phone":      { "connected": true, "battery": 64 },
  "messages": [
    { "id": "m17", "app": "whatsapp", "from": "Mihai", "state": "deferred",
      "deferred_reason": "high_speed", "replyable": true, "ts": 1763672390.0 }
  ],
  "call": null,
  "reminders": [
    { "id": "r1", "task": "lichid de parbriz",
      "trigger": { "type": "stop_at_category", "category": "fuel" },
      "state": "active", "created_ts": 1763671200.0 }
  ],
  "media":        { "playing": true, "track_id": "t07", "title": "…", "volume": 0.4,
                    "reason": "disengagement", "kid_safe": false },
  "intervention": { "last": "music_energetic", "effect_pct": 18,
                    "stats": { "music": 0.18, "delegate": 0.31, "quiz": 0.08 } },
  "ab":           { "naive_alerts": 7, "our_alerts": 1 },
  "blind_m":      { "last": 64, "trip": 180 },
  "scorecard":    { "longest_focus_min": 23, "hands_free_messages": 2, "phone_touches": 0,
                    "suggestions_accepted": 3, "suggestions_rejected": 1, "reminders_done": 1 },
  "integrations": { "phone_bridge": "ok", "twilio": "ok", "contact_app": "ok", "llm": "ok" },
  "perf": {
    "cameras": {
      "driver":    { "capture_fps": 30, "process_fps": 24, "dropped_frames": 3 },
      "passenger": { "capture_fps": 25, "process_fps": 10, "dropped_frames": 1 }
    },
    "face_driver_ms_p50": 9, "face_passenger_ms_p50": 8, "pose_ms_p50": 22,
    "phone_ms_p50": 18, "gesture_ms_p50": 7, "sface_ms_p50": 25,
    "e2e_ms_p95": 95, "alarm_ms_last": 120,
    "llm_ttft_ms": 640, "llm_total_ms": 1500, "stt_final_ms": 700, "tts_first_audio_ms": 400,
    "msg_to_voice_ms": 2100,
    "cpu": 61, "ram_mb": 2100, "gpu": 35
  }
}
```

**Explicații:**
- `occupants[].source`: `cam_driver`, `cam_passenger` sau `declared` (bancheta din spate, din voce sau din panou).
- `driver.phone.source`: `detector` (telefon văzut) sau `lap_pattern` (tiparul privirilor spre poală).
- `driver.gaze.source`: `face` (din reperele feței) sau `body` (regula pentru spate).
- `head.answer` și `passenger.answer`: `yes` / `no` / `null` (doar în fereastra de dialog).
- `messages[].app`: `sms`, `whatsapp` sau `contact_app`. `state`: `pending` / `deferred` / `read` / `replied`.
- `reminders[].state`: `proposed` (așteaptă confirmarea) / `active` / `done`.
- `assistant.muted_until`: până când tace asistentul după un refuz (`mute_reason: "driver_refused"`). Siguranța nu e afectată.
- `safe_contact`: vine din profil (numărul de telefon e doar în `.env`). `notified_ts` e ultima notificare și se folosește pentru cooldown.

Contractul stă în `shared/contracts.py` (Pydantic v2) și se schimbă doar cu acordul tuturor. Fiecare modul lucrează pe date false până e gata modulul de care depinde.

---

## 8. Computer vision: stack, filtrare, performanță

### Stack-ul decis
| Detecție | Metodă | Cameră |
|---|---|---|
| Față, ochi, căscat, cap, iris, buze | MediaPipe Face Landmarker pe decupajul feței | ambele |
| Zone de privire | unghiurile capului + iris → kNN pe calibrarea per șofer | șofer |
| Încheieturi (pentru telefon) | YOLO26n-pose | ambele |
| Telefon | YOLO26n doar pe clasa 67, pe zona mâinilor + geometria; tiparul „poală” la șofer | ambele |
| Identitate | OpenCV YuNet + SFace | ambele |
| Gesturi | MediaPipe Gesture Recognizer | ambele |
| Răspuns din cap | oscilații de pitch/yaw în fereastra de dialog | ambele |

**Simplificare datorată camerelor dedicate:** fără ByteTrack și fără atribuirea locurilor, pentru că pe fiecare cameră e o singură persoană.
**Nu folosim:** OpenPose, dlib, Haar cascades, ByteTrack, antrenare de la zero, LLM-uri cu viziune pe cadre, rPPG.
**Dacă telefonul e instabil după sâmbătă la 12:00:** ~150 de cadre proprii, făcute în montajul de demo, etichetate, plus o antrenare suplimentară a YOLO26n pe un GPU gratuit.

### Filtrarea în timp
- EMA pe unghiuri și EAR. **Histerezis** (de exemplu „închis” sub 0,18, „deschis” peste 0,23). Durată minimă a stării (~300 ms).
- Fața nu e găsită sau încrederea e mică → `unknown`, fără alertă.
- Ochii nu se văd → `eyes.reliable=false`, doar metrici de cap.
- **Pragurile stau în fișierele de configurare ale modulelor** (`perception/config/perception.yaml`, `core/config/thresholds.yaml`, `assistant/config/assistant.yaml`), niciodată în cod.

### Bugetul de calcul
| Model | Cameră | Frecvență | Țintă |
|---|---|---|---|
| Face Landmarker | șofer | fiecare cadru (≥20 fps) | ≤15 ms |
| Face Landmarker | pasager | 10 Hz | ≤15 ms |
| YOLO26n-pose (încheieturi) | ambele | 5 Hz | ≤30 ms |
| YOLO26n telefon (zona mâinilor) | ambele | 5 Hz | ≤20 ms |
| Gesture Recognizer | ambele | doar în fereastra de dialog / cu mâna ridicată | ≤15 ms |
| YuNet + SFace | ambele | la apariția unei fețe, reverificare la ~10 s | ≤30 ms |

### Regulile de performanță
1. Un thread de captură pe fiecare cameră, cu **doar ultimul cadru** (coadă de 1, `CAP_PROP_BUFFERSIZE=1`). Camera pasagerului prin **DroidCam pe USB** (latență mai mică și stabilă decât prin WiFi).
2. Face Landmarker pe decupaj, nu pe tot cadrul.
3. YOLO la 640 px. Video spre dashboard la 640 px, JPEG 70, 10–15 fps.
4. Export OpenVINO (Intel) / TensorRT sau ONNX (NVIDIA).
5. Warm-up la pornire: o inferență pe fiecare model, un apel LLM, vocile preîncărcate.
6. Alarmele, „Ești bine?”, instrucțiunile pentru pasager și mementourile de la oprire sunt clipuri sau șabloane, nu LLM.
7. LLM-ul rulează în cloud (nu ia CPU de la CV), cu un rezumat al stării de ~10 rânduri. Răspunsul vine în streaming, iar vocea pornește de la prima propoziție.
8. Percepția trimite la 15 Hz, core-ul spre UI la 10 Hz. orjson. Graficul fără animații, cu ultimele ~120 de puncte.
9. **Regula de degradare:** dacă latența cap-coadă p95 trece de 150 ms, scade întâi frecvența camerei pasagerului, apoi cea a YOLO. Fața șoferului nu se degradează niciodată.

### Țintele (pe dashboard și pe slide)
| Metrică | Țintă |
|---|---|
| FPS pe fața șoferului | ≥ 20 |
| Ochi închiși → alarmă | < 300 ms (ideal ~150 ms) |
| LLM → prima propoziție rostită | < 2 s |
| Mesaj primit pe telefon → citit cu voce (la risc 0) | < 3 s |
| Alerte false în scenariul de demo | 0 la DriveMate, comparat cu pragul simplu |
| Atingeri ale telefonului în demo | 0 |

---

## 9. Scenariul de demo

**Roluri:**
- **Șofer** („Andrei”). Telefonul lui Android e conectat prin KDE Connect.
- **Pasager în dreapta** („Maria”).
- **Regizor și prezentator** („Mihai”):
  - controlează panoul și vorbește cu juriul;
  - **trimite WhatsApp-ul** din scena 3;
  - **primește apelul SOS** din scena 9.
- **Al patrulea membru:**
  - ține pagina DriveMate Contact pe al doilea ecran;
  - opțional, e „copilul din spate” (declarat, doar voce).

**Montajul fizic:**
- Două scaune în față (al treilea în spate, dacă e cazul).
- Laptopul pe „bord”, cu webcam-ul spre șofer.
- Telefonul-cameră (DroidCam, USB) fixat spre scaunul din dreapta.
- Post-it-uri pentru oglinzi.
- Lampă proprie pe șofer.
- Ecran mare cu dashboard-ul și harta.

**Înainte de demo:**
- calibrarea e salvată în profil (panoul are o recalibrare de 15 s dacă se mută camera);
- telefonul lui Andrei e împerecheat, iar laptopul e pe hotspot-ul lui;
- tunelul e pornit și QR-ul paginii Contact e pe slide;
- warm-up făcut, clipurile audio încărcate.

**Pe toată durata se văd:** contorul A/B (H4), panoul de performanță (J1) și contorul „atingeri telefon”.

### Varianta principală (~4,5 minute)
| # | Drum | Ce se întâmplă | Ce arată sistemul | Funcții |
|---|---|---|---|---|
| 1 | Pornire, 0 km/h | Andrei și Maria se așază. Andrei: „Amintește-mi să iau lichid de parbriz când oprim la o benzinărie.” | „Salut Andrei. Salut Maria.” → „Notat: lichid de parbriz, la prima benzinărie. Bine?” → **Andrei dă din cap** → mementoul apare pe dashboard | AS10, AP1, K1, D9, E1, E3, AS8 |
| 2 | Oraș, 50 km/h | Andrei se uită în oglinda stângă. Apoi acoperă camera | „Oglindă ✓”, fără alertă. Contor: „prag simplu 1 · DriveMate 0”. Debug-ul (tasta D) arătat 10 s. „Nu te mai văd” | AS5, B8, H4, H1, AS12, C7 |
| 3 | Oraș | **Mihai trimite un WhatsApp real** pe telefonul lui Andrei. Telefonul vibrează, Andrei întinde mâna | „Lasă telefonul, ți-l citesc eu. Mesaj personal de la Mihai, îl citesc tare?” → dat din cap → citit. Andrei: „Spune-i că ajung în 20 de minute.” → „Îi scriu: «Ajung pe la 18:40.» Trimit?” → 👍 → **răspunsul apare în WhatsApp-ul lui Mihai** (arătat juriului). „Atingeri telefon: 0” | F1, F2, F3, AS7, D2, E3, B1, J3 |
| 4 | Oraș | Andrei și Maria vorbesc, apoi Maria îi arată ceva pe telefonul ei, iar Andrei se uită de 3 ori spre ea | Cât vorbesc: `stay_silent – conversație`. Apoi **cauza, din 2 camere**: „pasagerul arată telefonul” → „Maria, poți să-i povestești tu? Andrei, ochii pe drum.” → privirile spre dreapta scad → „Cauză rezolvată ✓ (+X%)”. Telefonul e la Maria, deci Andrei nu primește alertă de telefon (pragul simplu a mai dat una) | B9, G2, AP3, AP4, AS5, B4, D2, D6, G5, B8 |
| 5 | Autostradă, timp ×20 | Liniște. Privire fixă, răspunsuri lente | **D crește** pe grafic → „Pare monoton. Pun ceva mai energic, din ce-ți place?” → dat din cap → muzica pornește. Cât asistentul prezintă piesa, Andrei se uită în oglindă → **vocea se oprește în mijlocul frazei** și reia cu „...cum ziceam”. D scade, cardul arată efectul | B1, B2, D8, D4, D6 |
| 6 | Autostradă | Maria adoarme. Andrei cască, clipește lent. Când asistentul începe să-i vorbească, Andrei spune: „Lasă-mă în pace.” | Camera pasagerului: Maria doarme, deci muzica se dă încet. **F crește** (separat de D) → asistentul pornește o conversație: „Andrei, hai să vorbim puțin. Cât de obosit ești, 1–9?” → „Lasă-mă în pace.” → **„Ok, te las în pace. Îi dau de veste lui Mihai.”** → **SMS de pe telefonul lui Andrei către Mihai** (arătat juriului) + notificare galbenă pe DriveMate Contact → Mihai răspunde pe WhatsApp: „Oprește la o cafea, te rog!” → „Mesaj de la Mihai, îl citesc?” → dat din cap → citit încet → „Oprim la OMV peste 12 km? Iei și lichidul de parbriz.” → dat din cap | AP2, G3, B2, D3, D10, C10, F8, K3 |
| 7 | Benzinărie | Regizorul oprește mașina la POI | „Ai zis să iei lichid de parbriz.” → 👍 → mementoul e bifat pe hartă | K2, I1, I2 |
| 8 | Autostradă | **Regizorul oprește LLM-ul.** Andrei închide ochii | „ANDREI!” (latența afișată, ~140 ms) → „Ești bine?” → „Da.” → LLM-ul e repornit | C3, C4, C6 |
| 9 | Autostradă | Capul lui Andrei cade, nu mai răspunde. Maria se trezește de la alarmă | „Maria, Andrei nu răspunde. Pornește avariile…” → numărătoare → **telefonul lui Mihai sună pe difuzor** și se aude raportul + **SMS de pe telefonul lui Andrei** cu locația + **alertă roșie pe DriveMate Contact**, cu harta live | C5, F6, F5 |
| 10 | Final | — | **Fișa călătoriei:** cel mai lung interval concentrat, reacția vs. referință, metrii orbi pe hartă, mesaje fără mâini / 0 atingeri, alerte DriveMate vs. prag simplu, ce te-a ajutat (muzica +X%, delegarea +Y%) | J2, J3, B6, H6 |

### Varianta scurtă (~3 minute)
Scenele 1, 3, 4, 6 + 7 (pauza și oprirea, legate), 8, 9.

### Extra (doar dacă e timp)
- Ioana (declarată în spate): Andrei se întoarce spre ea → ghicitoare pentru copil, cu filtrul `kid_safe` (AS13, D2, G4).
- Juriul scrie din DriveMate Contact și primește răspunsul dictat (F7).
- Un apel primit pe telefonul lui Andrei → SMS automat „Conduc, te sun la oprire” (F4).

### Rezerva
Fiecare scenă are un flux JSON înregistrat la repetiții. Dacă CV-ul cedează live, regizorul trece pe redare din panou. Regulile, LLM-ul, vocea, telefonul, dashboard-ul și apelul rulează real.

---

## 10. Echipa: cine ce face, în ordine

> Instrucțiunile detaliate (unde lucrează fiecare, interfețele, cum se face fiecare pas) sunt în `roluri/P1-computer-vision.md`, `roluri/P2-context-siguranta.md`, `roluri/P3-llm-voce-telefon.md` și `roluri/P4-dashboard-simulator-contact.md`.

### P1: computer vision + performanța modelelor (`perception/`)
1. **În seara asta:** benchmark pe laptopul de demo cu ambele camere (webcam + DroidCam pe USB): fps pe model și latență. Thread de captură cu ultimul cadru.
2. Camera șoferului: Face Landmarker pe decupaj, EAR pe fiecare ochi, PERCLOS, microsomn, căscat, capul, căderea capului, buzele.
3. Calibrarea pe zone cu kNN (inclusiv `passenger`), salvată în profil.
4. Telefonul șoferului (zona mâinilor + geometria + tiparul „poală”), răspunsul din cap, gesturile, identitatea.
5. Camera pasagerului: identitate, treaz/adormit, buze, telefon, `present`.
6. VATS, entropia privirii, `monitoring_ok`, overlay-ul de debug, timpii din `perf`, `scripts/benchmark.py` (J4).
7. Duminică: reglarea pragurilor în sală.

### P2: context + siguranță + SOS (`core/`)
1. **Până la 00:30:** contractul v2 în `shared/contracts.py`, `thresholds.yaml`, `scripts/fake_perception.py` (cu taste pentru fiecare situație din scenariu, inclusiv pasagerul).
2. Arbitrul P0–P4, escaladarea, microsomn → alarmă → „Ești bine?” → anulare pe oricare canal.
3. Fluxul SOS: numărătoare, instrucțiuni pentru pasager, **apelul Twilio** (test în seara asta), declanșarea SMS-ului și a alertei din pagină, „Nu te mai văd”.
4. Reacția pe 3 canale, F, D, atenția, riscul, conversația (B9).
5. Cauza din 2 camere, regula de timing pentru mesaje, eficiența intervenției, pragul simplu (A/B).
6. Mementourile: declanșarea la oprire (K2) și alegerea opririi care rezolvă un memento (K3). Metricile pentru fișa călătoriei (J2, J3).
7. Regula contactului de încredere (C10): liniștea după refuz, SMS-ul cu cooldown, notificarea din pagină, șabloanele în `core/config/templates.yaml`.

### P3: LLM + voce + telefon (`assistant/`, `integrations/phone_bridge.py`, `dashboard/src/voice/`)
1. **În seara asta:**
   - testați STT în română în Google Chrome și vocile românești din edge-tts, apoi hotărâți limba;
   - **împerecheați KDE Connect** cu un Android: notificare WhatsApp citită, răspuns trimis, SMS trimis.
2. Clientul LLM: rezumatul stării, promptul de sistem, validarea acțiunilor, timeout + texte fixe, streaming.
3. Vocea: half-duplex, fereastra de dialog de 6 s, latența verbală (WebAudio), fuziunea da/nu pe toate canalele, clipurile pregenerate (E7).
4. Puntea cu telefonul (F1, F3): notificări pe D-Bus, lista albă, răspuns WhatsApp/SMS, SMS-ul SOS.
5. Vorbirea care cedează drumul (D4). Remediile: delegare, „ți-l citesc eu”, KSS + pauză, **muzica recomandată** (D8, `media_catalog.json` cu ~20 de piese fără drepturi de autor, etichetate).
6. Mementourile prin voce (K1, D9) și reformularea răspunsurilor (cu ETA).
7. Conversația anti-oboseală și recunoașterea refuzului (D10), clipurile „Ok, te las în pace.” și „Îi dau de veste lui {contact}.”, trimiterea SMS-ului către contactul de încredere prin punte și citirea răspunsului (F8).

### P4: dashboard + simulator + DriveMate Contact (`dashboard/`, `simulator/`, `integrations/contact_app/`)
1. **În seara asta:** scheletul repo-ului (promptul pentru Claude Code), primul commit, **DriveMate Contact minimal + tunelul `cloudflared` testat de pe un telefon pe date mobile**.
2. Dashboard pe date false: ambele video cu overlay, graficul cu 3 linii, jurnalul, contorul A/B, ocupanții, mesajele, mementourile.
3. **Panoul de performanță (J1) și fișa călătoriei (J2, J3).**
4. Simulatorul: traseu + `stops.json` cu POI-uri pe categorii + harta Leaflet (POI-uri, mementouri, metri orbi, SOS).
5. Panoul regizorului: salt la scenă, timp accelerat, viteză, oprire la POI, oprirea LLM-ului, ocupanți declarați, resetare. Înregistrarea și redarea fluxului JSON.
6. DriveMate Contact complet: starea șoferului, mesaje, **notificarea galbenă „obosit”** (contactul de încredere), alerta SOS cu harta live. Contactele (de încredere, de urgență) și acordul în `profiles/<nume>/profile.json`, iar numerele în `.env`. Prezentarea `.pptx` pe template, README-ul final, QR-ul.

---

## 11. Programul

### Vineri noaptea (acum → 02:00)
| Ora | Cine | Ce |
|---|---|---|
| 23:00–23:15 | toți | citit planul v2, confirmat, ales laptopul de demo și telefonul Android al „șoferului” |
| 23:15–00:15 | P4 | scheletul repo-ului + primul commit (făcut de om) |
| până la 00:30 | P2 | **contractul v2 închis** |
| 23:15–02:00 | P1 | benchmark cu 2 camere (DroidCam pe USB), test de detecție a telefonului |
| 23:15–02:00 | P2 | test Twilio (apel spre un număr românesc; dacă apare mesajul contului de probă, contul trece pe plată) |
| 23:15–02:00 | P3 | test STT/TTS în română, test KDE Connect (citire + răspuns WhatsApp + SMS), primul apel LLM cu acțiuni validate |
| 23:15–02:00 | P4 | pagina Contact minimă + tunelul testat de pe date mobile |
| 02:00 | toți | **punct de control:** contract, commit, Twilio, KDE Connect, tunel, telefon (CV), limba vocii |

**Somnul pe rânduri:** câte doi oameni dorm o dată, minimum 4 ore fiecare până sâmbătă dimineață.

### Sâmbătă
| Ora | Punct de control |
|---|---|
| 12:00 | **Fluxul cap-coadă merge:** cameră → context → regulă → alarmă în browser; LLM → voce; notificare de pe telefon → citită cu voce; dashboard live |
| 12:00–22:00 | Funcțiile M, **în ordinea scenelor de siguranță întâi**: 8 și 9 (alarmă, SOS), apoi 2 (oglinda + contorul), 3 (telefonul), 4 (cauza din 2 camere), 5–7 (D + muzică, F + pauză, memento), 1 (salut + memento), 10 (fișa) |
| 22:00 | **Toate funcțiile M merg. După ora asta nu se mai adaugă nimic** |
| 22:00–02:00 | integrare, buguri, înregistrarea fluxurilor JSON pentru fiecare scenă, benchmark-ul pentru slide |

### Duminică
- Repetiții în sală (minimum 3 rulări complete), reglarea `thresholds.yaml` pe lumina reală.
- Testul A/B real pentru slide: prag simplu vs. DriveMate, 5 minute de condus normal cu oglinzi.
- `.pptx` pe template-ul oficial, README-ul final. **Fără video**: rezerva e redarea JSON.

---

## 12. Structura repo-ului (`AI_SkodaRapid`)

```
AI_SkodaRapid/
├── README.md                  # P4, în engleză
├── .gitignore                 # CLAUDE.md, CLAUDE.local.md, .claude/, .env, modele, embedding-uri, media, jurnale
├── .env.example               # LLM, TWILIO_*, CONTACT_TOKEN, KDECONNECT_DEVICE_ID, EMERGENCY_NUMBER, SAFE_CONTACT_NUMBER, CORE_URL
├── requirements.txt           # doar include requirements/p*.txt (P4)
├── requirements/              # p1-perception.txt, p2-core.txt, p3-assistant.txt, p4-dashboard.txt
├── run.sh
├── shared/
│   └── contracts.py           # contractul v2 (toți, doar de comun acord)
├── perception/                # P1
│   ├── main.py
│   ├── capture.py             # thread cu ultimul cadru, per cameră
│   ├── filters.py             # EMA, histerezis, durată minimă
│   ├── driver_cam/            # face.py, eyes.py, head.py, gaze_zones.py, calibration.py, head_answer.py,
│   │                          # gestures.py, phone.py, identity.py, speaking.py
│   ├── passenger_cam/         # face.py, awake.py, speaking.py, phone.py, identity.py
│   ├── config/perception.yaml # pragurile de percepție
│   ├── perf.py
│   ├── stream.py              # MJPEG cu overlay de debug
│   └── models/                # gitignored
├── core/                      # P2
│   ├── main.py                # FastAPI: /ws/perception, /ws/ui, /ws/phone; montează contact_app și assistant.router
│   ├── state/
│   ├── scoring/               # reaction.py, fatigue.py, disengagement.py, attention.py, risk.py, conversation.py
│   ├── cause.py               # fuziunea celor 2 camere
│   ├── safety/                # arbiter.py, escalation.py, sos.py, monitoring.py
│   ├── messages_timing.py
│   ├── reminders.py           # declanșare la oprire, alegerea opririi
│   ├── intervention.py
│   ├── ab_baseline.py
│   ├── scorecard.py           # J2, J3
│   ├── safe_contact.py        # C10
│   └── config/                # thresholds.yaml, templates.yaml (SOS, contact de încredere, mementouri)
├── assistant/                 # P3
│   ├── client.py
│   ├── actions.py
│   ├── prompts/
│   ├── policies.py
│   ├── fallback.py
│   ├── memory.py
│   ├── music.py               # recomandarea pentru D
│   ├── refusal.py             # recunoașterea refuzului (D10)
│   ├── summary.py             # starea → ~10 rânduri pentru LLM
│   ├── router.py              # /tts/… (montat de core)
│   ├── config/assistant.yaml
│   └── data/                  # media_catalog.json, riddles.json (media/ e gitignored)
├── integrations/
│   ├── phone_bridge.py        # P3: KDE Connect (D-Bus), notificări, răspuns WhatsApp/SMS
│   ├── twilio_call.py         # P2: apelul SOS
│   ├── audio_clips.py         # P3: pregenerează clipurile
│   └── contact_app/           # P4: pagina DriveMate Contact (HTML + WS + Leaflet)
├── simulator/                 # P4
│   ├── route.json
│   ├── stops.json             # POI-uri cu categorii
│   ├── simulator.py
│   ├── director.py
│   └── replay.py              # înregistrare/redare flux JSON
├── dashboard/                 # P4 (+ P3 în src/voice/)
│   ├── src/components/        # video, grafic, jurnal, A/B, performanță, fișa călătoriei, hartă, ocupanți
│   ├── src/voice/
│   └── public/sounds/
├── profiles/<nume>/           # profile.json (P4); calibration.json și face.npy scrise la rulare de P1 (gitignored)
├── scripts/                   # download_models.sh, enroll_face.py, calibrate.py, benchmark.py (P1) · fake_perception.py (P2) · fake_core.py (P4)
├── tests/                     # perception/ (P1), core/ (P2), assistant/ (P3), dashboard/ + scenes/ (P4)
├── docs/                      # perception.md (P1), core.md (P2), assistant.md (P3), restul (P4)
└── presentation/
    └── AI_SkodaRapid.pptx
```

`roluri/` și documentele de strategie stau în afara repo-ului (în `.gitignore`) până duminică.

---

## 13. Reguli de lucru și sincronizare

Instrucțiunile pe rol sunt în `roluri/`. Fiecare citește planul ăsta și fișierul rolului său.

### Unde lucrează fiecare
Când cineva are nevoie să schimbe ceva în zona altcuiva, anunță pe grup, ca să nu lucreze doi oameni în același fișier în același timp.

| Rol | Lucrează în principal în |
|---|---|
| **P1** | `perception/**`, `scripts/{benchmark,enroll_face,calibrate}.py`, `scripts/download_models.sh`, `tests/perception/**`, `docs/perception.md`, `requirements/p1-perception.txt` |
| **P2** | `core/**`, `shared/**`, `integrations/twilio_call.py`, `scripts/fake_perception.py`, `tests/core/**`, `docs/core.md`, `requirements/p2-core.txt` |
| **P3** | `assistant/**`, `integrations/phone_bridge.py`, `integrations/audio_clips.py`, `dashboard/src/voice/**`, `dashboard/public/sounds/**`, `tests/assistant/**`, `docs/assistant.md`, `requirements/p3-assistant.txt` |
| **P4** | `dashboard/**` (în afară de vocea din `dashboard/src/voice/`, făcută de P3), `simulator/**`, `integrations/contact_app/**`, `integrations/__init__.py`, `profiles/**`, `scripts/fake_core.py`, `tests/dashboard/**`, `tests/scenes/**`, `presentation/**`, restul din `docs/`, fișierele din rădăcină (`README.md`, `run.sh`, `.env.example`, `.gitignore`, `requirements.txt`) |

- **Fiecare modul are configurarea lui** (`perception.yaml`, `thresholds.yaml`, `assistant.yaml`). Niciun prag în cod.
- **Dependențele sunt pe roluri:** `requirements/pX-….txt`. Fișierul `requirements.txt` din rădăcină doar le include.
- **Cine consumă își scrie singur datele false:**
  - P2 scrie `fake_perception.py`;
  - P4 scrie `fake_core.py`;
  - P3 folosește stările din `tests/assistant/fixtures/`.

### Interfețele dintre module (toate tipurile sunt în `shared/contracts.py`)
| Interfață | Între | Ce circulă |
|---|---|---|
| `ws://localhost:8000/ws/perception` | P1 ↔ core | `PerceptionFrame` (15 Hz) → core; comenzi `dialog_window`, `calibrate`, `debug`, `enroll` → P1 |
| `http://localhost:8001/video/{driver,passenger}` | P1 → dashboard | MJPEG, 640 px |
| `ws://localhost:8000/ws/ui` | core ↔ browser (UI-ul lui P4 + vocea lui P3) | → browser: `state` (10 Hz), `event`, `speak`, `speak_control`, `alarm`, `media` · → core: `command`, `speech`, `speech_onset`, `speak_done`, `alarm_played` |
| `assistant.handle_event(event, state) -> list[Action]` | core → P3 (în proces) | evenimente → acțiuni, validate de P2 |
| `assistant.refusal.is_refusal(text) -> bool` | core → P3 (în proces) | refuzul din dialogul de oboseală |
| `assistant.router` | P3, montat în core | `/tts/{id}.mp3` |
| `ws://localhost:8000/ws/phone` | puntea lui P3 ↔ core | `phone_message`, `call`, `phone_status` → core · `send_reply`, `send_sms` → punte |
| `integrations.contact_app` | P4, montat în core | `router`, `push_status`, `push_safe_contact`, `push_sos`; mesajele din pagină → core |
| `simulator.Simulator` | core → P4 (în proces) | `tick() -> Trip`, `command(cmd)` |
| `integrations.twilio_call.place_sos_call(report)` | P2 | apelul SOS |

### Cum se schimbă contractul
1. Mesaj pe grup: `CONTRACT: <câmp>, <tip>, <cine îl scrie>, <de ce>`.
2. Câmpul se adaugă **opțional, cu valoare implicită**, ca să nu strice pe nimeni. Apoi se crește `CONTRACT_VERSION` și se actualizează `tests/core/fixtures/state_example.json`.
3. Schimbarea intră direct în `main` (excepție de la punctele de control) și se anunță. Ceilalți fac `git merge origin/main`.
4. Până duminică nu se redenumesc și nu se șterg câmpuri.

### Git
- O ramură pe rol: `p1-perception`, `p2-core`, `p3-assistant`, `p4-dashboard`.
- **Commit pe fiecare funcție** (e în cerințe). Mesaj în engleză, la imperativ, cu prefixul modulului: `perception: add PERCLOS window`, `core: add SOS countdown`.
- Înainte de fiecare punct de control, în ramura ta:
  ```bash
  git fetch origin && git merge origin/main      # aduci ce au integrat ceilalți
  pytest -q tests/<modulul-tău>                  # + modulul tău pornit pe date false
  git push origin <ramura-ta>
  ```
- La punctul de control, pe rând, **P2 → P1 → P3 → P4**:
  ```bash
  git checkout main && git pull
  git merge --no-ff <ramura-ta>
  ./run.sh --fake                                 # pornește? atunci:
  git push origin main
  ```
- Cheile (LLM, Twilio), tokenul paginii Contact, numerele de telefon și ID-ul dispozitivului KDE Connect stau doar în `.env`. **Repo-ul e public.**

**Claude Code**
- `CLAUDE.md` și `.claude/` sunt în `.gitignore` și se dau între noi direct, nu prin git.
- **Claude nu face niciodată commit sau push.** Regula e impusă pe trei niveluri: instrucțiunea din CLAUDE.md, regulile de interdicție din `.claude/settings.json` și hook-urile git locale (`bash .claude/install-git-guard.sh`, o dată după clonare).
- După ce se creează CLAUDE.md și `.claude/settings.json`, sesiunea de Claude Code trebuie repornită ca să le încarce.
- La scheletul repo-ului, contractul din promptul pentru Claude Code se înlocuiește cu cel din **secțiunea 7** a acestui document.
- Fiecare își pune în `CLAUDE.local.md` (personal, în `.gitignore`) blocul din fișierul rolului său, ca Claude să știe pe ce lucrează fiecare.

**Sincronizare:** 10 minute la fiecare punct de control. Ce nu e în scenariu nu se construiește.

---

## 14. Riscuri și soluții

| Risc | Soluție |
|---|---|
| Lumina din sală | Lampă proprie pe șofer; repetiții în sală; calibrare pe montajul real |
| Telefonul șoferului în poală nu se vede din webcam | Tiparul „poală” (priviri repetate spre poală), cu încredere mai mică; în demo, telefonul e ridicat la vedere |
| Detecția telefonului instabilă | Zona mâinilor + geometria; antrenare suplimentară pe ~150 de cadre proprii |
| DroidCam lent sau se deconectează | USB, nu WiFi; thread cu ultimul cadru; dacă cade, sistemul continuă doar pe camera șoferului și anunță |
| KDE Connect nu vede telefonul (WiFi-ul din sală izolează dispozitivele) | Hotspot-ul telefonului șoferului sau tethering USB; firewall deschis; test vineri |
| Răspunsul pe WhatsApp din notificare nu merge | Rezervă: SMS cu `kdeconnect-cli --send-sms`; test vineri |
| Telefon iPhone | Nu e suportat. Folosim un Android, scris pe slide-ul de viziune |
| Tunelul `cloudflared` cade | Repornire (URL nou, QR regenerat din panou); rezervă: pagina pe rețeaua locală |
| Prea mult de procesat | Bugetul pe frecvențe; regula de degradare (camera pasagerului cedează prima); laptop cu GPU |
| CV-ul cedează live | Redarea fluxului JSON pe scenă (I3) |
| LLM lent sau WiFi picat | Timeout + texte fixe; hotspot; siguranța nu depinde de rețea |
| STT nu merge pe Linux | Google Chrome, nu Chromium; test vineri; rezervă: engleză |
| Ecoul (asistentul se aude singur) | Half-duplex |
| Vocea română sună robotic | edge-tts cu voce românească; clipuri pregenerate pentru tot ce e critic |
| Twilio: mesajul contului de probă / nu sună în România | Test vineri; permisiunile geografice activate; cont trecut pe plată; rezervă: SMS de pe telefon + pagina Contact |
| Dat din cap confundat cu căderea capului | Doar în fereastra de dialog, rapid (<1,2 s), cu ochii deschiși |
| Entropia mică în trafic solicitant | D contează doar în context monoton și cu F mic |
| Muzica pornește într-un moment prost | Doar la P4, cu confirmare; se oprește la orice alertă; volum mic dacă pasagerul doarme |
| Contorul A/B pare trucat | Pragul simplu = același detector, fără zone, calibrare sau context; scris pe slide |
| „+X%” pe prea puține date | Ferestre configurabile; „efectul măsurat în această sesiune” |
| Contactul de încredere primește prea multe mesaje | Doar cu F peste prag **și** refuz explicit; cel mult unul la `cooldown_min` |
| Șoferul se simte urmărit | Acord dat la configurare; asistentul spune că anunță contactul (`announce`, implicit pornit) |
| WhatsApp nu poate începe o conversație nouă | Mesajul către contact pleacă pe SMS. Răspunsul poate veni pe orice canal |
| Doi oameni modifică același fișier | Configurări și dependențe separate pe roluri; anunț pe grup înainte de a lucra în zona altcuiva |

---

## 15. Prezentarea (pe template-ul oficial, ~9 slide-uri)

1. **Problema:** ADDW obligatoriu din iulie 2026, dar doar pe mașini noi; șoferii opresc sistemele din cauza alertelor false. Skoda Rapid 2014.
2. **Soluția:** DriveMate, cu cele 3 inovații.
3. **Arhitectura:** calea rapidă vs. calea lentă, P0–P4, veto, cele două camere.
4. **Demo live.**
5. **Pipeline-ul de computer vision + cifrele de performanță** (J1, J4).
6. **„Zero atingeri”:** telefonul conectat, mesajele, mementourile, DriveMate Contact.
7. **Testul A/B:** prag simplu vs. DriveMate + efectul intervențiilor (J3).
8. **Confidențialitate:** formularea exactă din secțiunea 3.
9. **Viziunea:** tot ce am tăiat (Apple Watch, CarPlay, Spotify, iPhone, rPPG, a treia cameră pentru spate, eCall real).

---

## 16. Ce am tăiat

Apple Watch, CarPlay / Android Auto real, Spotify API (folosim mp3-uri locale), Telegram (înlocuit de DriveMate Contact), iPhone ca telefon conectat, rPPG, copilul uitat în mașină, camera pentru bancheta din spate, RAG complex, apelul la 112, LLM local, imagini trimise la LLM, video înregistrat. Toate apar pe slide-ul de viziune.

---

## Surse

- ADDW obligatoriu în UE din 7 iulie 2026: https://smarteye.se/news/advanced-driver-distraction-warning-systems-now-mandatory-across-all-new-eu-vehicles/
- Euro NCAP 2026, monitorizarea șoferului: https://smarteye.se/blog/driver-monitoring-euro-ncap-2026/
- Euro NCAP, Driver Monitoring Dossier Guidance (priviri, VATS): https://www.euroncap.com/media/91718/sd-201-driver-monitoring-dossier-guidance-v11.pdf
- Which?, 32% își opresc sistemele: https://www.which.co.uk/policy-and-insight/article/car-safety-tech-driving-motorists-round-the-bend-which-finds-avra32B7heXH
- What Car? / GB News, sisteme intruzive: https://www.gbnews.com/lifestyle/cars/british-drivers-turning-off-eu-safety-features-warning
- ANCAP, sisteme adaptive: https://www.carexpert.com.au/car-news/tired-of-your-car-constantly-beeping-ancap-is-too
- CHI 2026, „Small Talk, Big Impact?”: https://arxiv.org/abs/2510.25421v1
- Asistent LLM pe voce și încărcarea cognitivă: https://arxiv.org/abs/2601.15034v1
- YOLO26 (Ultralytics): https://docs.ultralytics.com/models/yolo26/
- KDE Connect: https://kdeconnect.kde.org/
- Detectarea copiatului prin postură (YOLOv8-pose, praguri dinamice): https://www.mdpi.com/2673-4052/6/4/82
- Victor, Harbluk & Engström (2005), „Sensitivity of eye-movement measures to in-vehicle task difficulty”, Transportation Research Part F

Verificați fiecare cifră în sursă înainte s-o puneți pe slide.
