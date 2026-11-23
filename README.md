# Planspiel Börse: 15-Minuten-Gesamtportfolio für Pterodactyl

Privater Webserver für Safari, betrieben über ein Pterodactyl-Egg. Baut über GitHub Actions das Docker-Image `ghcr.io/playerlats9712/planspiel-portfolio:latest`.

## Auf dem iPad einrichten

1. Erstelle auf GitHub unter `playerlats9712` ein Repository namens `planspiel-portfolio`.
2. Lade **den Inhalt** des GitHub-Pakets hoch (nicht das ZIP als einzelne Datei). Wichtig: `.github/workflows/docker-image.yml` muss in genau diesem Pfad liegen.
3. Im Tab **Actions** den Workflow `Build and publish portfolio server` starten. Der Build muss erfolgreich sein.
4. Unter GitHub-Profil > Packages > `planspiel-portfolio` > Package settings > Change visibility das Paket auf **Public** setzen, sonst meldet Pterodactyl beim Download `denied`. Das Repository kann public sein, ohne dass das Package public ist.
5. Im Pterodactyl-Admin-Panel das mitgelieferte `egg-planspiel-portfolio.json` als Egg importieren, dann einen Server damit erstellen.
6. In den Startup-Variablen `PLANSPIEL_EMAIL`, `PLANSPIEL_PASSWORD`, `PLANSPIEL_DEPOT_ID`, `WEB_PASSWORD` eintragen. `WEB_USER` ist optional. Das Passwort und die E-Mail **nicht** bei GitHub eintragen.
7. Port zuweisen, Server starten, die Zuweisungsadresse im Browser öffnen. Für vollständige Sicherheit unbedingt HTTPS oder VPN vor Zugriff aus der Schule einrichten.

## Datenerfassung

- Alle 60 Sekunden wird der **gesamte Depotwert** aus `portfolio/getPortfolioWithItems` gespeichert. Die API-Struktur wurde aus deiner HAR-Datei abgeleitet.
- Aus den tatsächlichen Messwerten werden 15-Minuten-OHLC-Kerzen gebildet. Vor dem ersten Messwert gibt es keine Kerzen. Bei einem einzelnen Messwert in einem Intervall sind Open, High, Low, Close gleich.
- Der `getDepotValues`-Endpunkt liefert separate historische Depotstände, häufig nur täglich. Diese werden **nicht** als 15-Minuten-Kerzen ausgegeben.
- Die Daten liegen in SQLite unter `/home/container/data/portfolio.sqlite3`. Für dauerhafte Speicherung diesen Ordner bei Server-Neuerstellungen sichern.
- Diese API ist keine offiziell zugesicherte öffentliche Schnittstelle. Die Authentifizierung in HAR ist nachweisbar, die Authentifizierung der nachfolgenden Aufrufe muss ggf. auf deinem Server getestet werden. Dafür gibt es `API_AUTH_MODE` mit `bearer` (Standard), `x-bywo-jen` und `none`.

## Sicherheit

**Die HAR-Dateien und Login-Informationen gehören nicht in das GitHub-Repository.** Zugangsdaten und Tokens werden nicht auf Disk gespeichert. Im Egg hinterlegte Umgebungsvariablen können Pterodactyl-Administratoren sehen und der Docker-Prozess kann sie lesen. Das Webinterface ist mit Basic Auth geschützt; **ohne HTTPS ist diese Authentifizierung nicht sicher**. Lege nie den HTTP-Port öffentlich frei, solange du Anmeldedaten oder Depotinformationen schützen möchtest.

Das in der Login-HAR enthaltene Passwort und die Tokens sollten als kompromittiert betrachtet und bei Planspiel Börse geändert beziehungsweise widerrufen werden.
