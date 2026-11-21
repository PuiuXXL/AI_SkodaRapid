# DriveMate — plan de redesign

## Direcția artistică

La intrare, șoferul vede de aproape irisul argintiu al copilotului, tăiat de marginea cadrului. Înainte de plecare, centrul ecranului îi aparține drumului. În mers, următoarea oprire și vocea primesc tot spațiul. După sosire, același traseu devine cuprinsul călătoriei. Această succesiune leagă paginile chiar și cu toate animațiile dezactivate.

Din imaginea atașată preluăm trei decizii de compoziție: navigarea îngustă în stânga, o figură centrală suficient de mare pentru a fi citită și un panou lateral care explică selecția. În DriveMate, graficul central are sens la Monitorizare, harta la Drum, iar lista de conversații la Mesaje. Inelele procentuale din referință au sens numai pentru o mărime cu interval și unitate cunoscute.

Lusion își descrie practica prin povestire vizuală 3D și interacțiune. Traducerea propusă pentru DriveMate este regia cadrului: un obiect recognoscibil, lumină direcțională și o schimbare de scară care explică trecerea dintre momentele călătoriei. Prima probă folosește irisul SVG deja desenat și geometria reală a traseului. [Lusion](https://lusion.co/)

## Compoziția de bază

Astăzi, în La volan, discul și titlul piesei au propriul panou mare chiar și când muzica este oprită. În noua compoziție, următoarea oprire ocupă centrul, piesa devine un rând compact, iar detaliile selectate au un loc previzibil. Pe desktop, schița pentru o călătorie pregătită arată astfel:

```text
  Meniu flotant       La volan                         Simulat · conectat
 ┌──────────────┐    ┌──────────────────────────────┬─────────────────────┐
 │ La volan     │    │ Următoarea oprire            │ Detaliul opririi    │
 │ Drum         │    │ Numele locului               │ ETA, dacă există   │
 │ Muzică       │    │                              │ Memento asociat    │
 │ Mesaje       │    │ ───●───────────────○────     │                     │
 │ Fișa         │    │ Traseul și poziția raportată │ Începe călătoria    │
 │              │    ├──────────────────────────────┴─────────────────────┤
 │ Instrumente  │    │ Piesa curentă                 Starea copilotului   │
 │ Profil       │    └────────────────────────────────────────────────────┘
 └──────────────┘
```

- **Desktop larg, de la 1280 px.** Meniul are două lățimi controlate de utilizator. Zona centrală ocupă spațiul disponibil. Inspectorul are aproximativ 300 px și apare unde o selecție are detalii. Titlul, figura și legenda au aceeași margine stângă.
- **Tabletă, 768–1279 px.** Detaliile coboară imediat sub selecție. Dacă meniul extins îngustează excesiv graficul, schimbarea de compoziție se face după lățimea conținutului. Preferința utilizatorului pentru meniu rămâne activă.
- **Telefon, sub 768 px.** Navigația devine sertar. Ordinea de lectură este titlu, informație principală, acțiune, detalii. La Mesaje, selectarea conversației deschide un singur fir cu revenire la listă și la focusul anterior.
- **În mers.** Un singur cadru cu următoarea oprire, starea vocii și piesa. O alertă prioritară devine imediat elementul dominant. Trecerea la acest cadru urmează starea călătoriei comunicată de sesiune.

## Material, tipografie și mișcare

| Element | Decizie aplicabilă în cod |
| --- | --- |
| Fundal și suprafețe | Folosim tokenurile existente pentru fundalul aproape negru, suprafețele grafit și textul cald. Sticla se concentrează în meniul flotant și suprapuneri. În liste, un separator fin și alinierea coloanelor înlocuiesc conturul fiecărui element. |
| Accent | Argintiul din landing `--ui-accent` marchează punctul selectat și acțiunea principală. Avertizarea și SOS își folosesc culorile semantice, simbolul și textul propriu. Irisul își ia reflexele din familia existentă `--optic-*`. |
| Tipografie | Un titlu amplu pe Connect și Fișă, un titlu compact în instrumente. Valori cu cifre tabulare și unități lipite de valoare. În prototip verificăm explicit nume românești lungi, diacritice și ETA indisponibilă. |
| Tranziții | La Connect, irisul mare lasă loc interfeței printr-o singură estompare. La selectarea unei opriri, marcajul și titlul inspectorului se actualizează împreună. Folosim Motion existent și duratele de 140/220 ms din temă. |
| Randare | Traseul se redesenează când se schimbă geometria. Poziția actualizează doar marcajul. În mers, în filă ascunsă și cu mișcare redusă, scena rămâne statică între actualizările necesare. Alerta, textul și comenzile sunt disponibile din primul cadru. |

## Restructurarea paginilor

| Pagină | Ce domină cadrul | Interacțiunea care justifică structura |
| --- | --- | --- |
| Connect | Irisul în dreapta, numele și Connect pe o suprafață liberă în stânga. Pe telefon, irisul este decupat în partea superioară. | Prima conectare deschide configurarea profilului, următoarea deschide La volan. Butonul este disponibil imediat. |
| La volan | Traseul înainte de plecare, următoarea oprire în mers, mementoul relevant la oprire. | Acțiunea principală urmează faza confirmată. La sosire, confirmarea încheierii deschide fișa. |
| Drum | Hartă schematică amplă cu opriri numerotate și o listă în aceeași ordine. | Selectarea unui punct pe hartă sau din listă deschide același detaliu cu POI și memento. Dacă lipsește poziția, traseul rămâne lizibil fără marcaj de vehicul. |
| Muzică | Titlu și disc în zona de redare, bibliotecă în rânduri dedesubt. | Selectarea piesei arată sursa și disponibilitatea. Titlul redat se actualizează după confirmarea playerului. |
| Mesaje | Lista de expeditori și firul selectat, cu ultima stare lângă mesaj. | Citirea, ciorna și confirmarea trimiterii ocupă același loc în fir, în ordinea acțiunilor. |
| Profil și meniu utilizator | Avatarul din baza meniului deschide accesul rapid la profil, sunet și revenirea la volan. Pagina Profil are un index Eu / Copilot / Contacte / Conexiuni și un singur formular vizibil. | În modul restrâns, meniul apare lângă avatar. La salvare, confirmarea se afișează lângă câmpuri. Acordul pentru contact rămâne explicit. |
| Fișa călătoriei | O observație măsurată deschide pagina, urmată de traseu și cronologie. | Selectarea unui eveniment arată cauza și efectul disponibil. Comparația apare când există două fișe comparabile. |
| Monitorizare | Graficul semnalului selectat și jurnalul împart aceeași axă a timpului. Camerele rămân accesibile în zona de monitorizare. | Selectarea unui eveniment arată detecția și răspunsul asociat prin date. Dacă asocierea lipsește, inspectorul afișează doar informațiile cunoscute. |
| Simulator și regie | Traseul de editat în centru, scenele și comenzile în dreapta, starea execuției sub ele. | Operatorul poate urmări rezultatul unei scene în timp ce păstrează selecția și controalele la vedere. |
| Contact | O singură coloană cu starea călătoriei, ETA și formularul de mesaj. | În SOS, alerta și poziția autorizată urcă înaintea formularului. Pagina folosește exclusiv datele permise de token. |

## Ordine de implementare și probe

| Etapă | Livrare în proiect | Criteriu de acceptare |
| --- | --- | --- |
| 1. Proba de direcție | Trei cadre cu date simulate explicite: Connect, La volan înainte de plecare și La volan în mers. Folosim `Optic.tsx`, `DrivingPages.tsx` și `RouteDiagram.tsx`. Capturăm pentru comparație ecranele actuale și prototipul la 390 și 1440 px. | La prima privire se identifică următoarea oprire și acțiunea disponibilă. În mers, alerta este lizibilă imediat cu mișcarea dezactivată. |
| 2. Structura comună | În `DriverApp.tsx`, `NavigationShell.tsx` și `driver.css` introducem grila adaptivă, zona de detalii și meniul utilizatorului. Sesiunea și audio rămân la nivelul aplicației. | Meniul funcționează extins, restrâns și în sertar. Escape restaurează focusul. Navigarea păstrează redarea și ciornele. |
| 3. Fluxul șoferului | Implementăm Drum, Muzică, Mesaje și Profil pe noua structură. Pentru fiecare pagină pregătim stările cu date, fără date, date expirate și comandă în așteptare. | O ciornă începută la oprire reapare după mers. O comandă Live indisponibilă este identificabilă. Selecția pe hartă funcționează și din tastatură. |
| 4. Analiză și regie | Migrăm Fișa, Monitorizarea și Simulatorul. Refolosim vizualizările de scor, traseu și camere. Verificăm cu o scenă completă și un raport cu date lipsă. | Se poate urmări același eveniment din jurnal până la detaliul disponibil. Unitățile, intervalele și golurile din date se citesc la ambele densități. |
| 5. Contact și validare finală | Aplicăm compoziția mobilă paginii cu token și verificăm întregul flux la 390, 768 și 1440 px, la zoom 200%, din tastatură și cu mișcare redusă. | Build și teste din `dashboard` trecute. Fără derulare orizontală a paginii la zoom. Comparăm timpul de răspuns la comenzi și randarea Monitorizării cu măsurătorile inițiale pe același dispozitiv și aceeași scenă. |

Prima decizie de revizie se ia după etapa 1, pe baza celor trei cadre puse alături. Dacă irisul atrage privirea înaintea opririi pe ecranul de condus, îi reducem prezența acolo și păstrăm prim-planul pentru Connect. Astfel putem decide direcția artistică înainte de migrarea tuturor formularelor și instrumentelor.

Planul completează fluxurile descrise în [experiența șoferului](experienta-sofer.md) și folosește [sistemul DriveMate Graphite al proiectului](obsidian-orange.md).
