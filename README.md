# DealScout - Supermarket Deals Search (Edeka)

DealScout ist eine moderne Web-Applikation zur Suche von wöchentlichen Supermarkt-Angeboten (beginnend mit Edeka), implementiert mit Python (FastAPI), SQLite und HTMX in einem Docker-Container.

Die Anwendung zeichnet sich durch ein ansprechendes, reaktives Dark-Mode-Design (Glassmorphism-Optik) und extrem schnelle Suchzeiten dank lokalem Caching aus.

## Features

- **Marktsuche:** Suche nach Edeka-Filialen per Postleitzahl oder Stadtname.
- **Angebote-Suche:** Live-Suche (Search-as-you-type) in den aktuellen Wochenangeboten des ausgewählten Marktes.
- **Preis-Vergleich:** Übersichtliche Darstellung von regulärem Preis, App-exklusiven Sonderpreisen, Rabattprozenten und Grundpreisen.
- **Caching:** Wöchentliche Angebote werden in einer lokalen SQLite-Datenbank gecached, um Edeka-Server nicht zu überlasten und die Suche blitzschnell zu machen.
- **Dockerisiert:** Vollständiges Docker- und docker-compose-Setup.

## Technologien

- **Backend:** Python, FastAPI, Uvicorn, SQLModel (SQLite), BeautifulSoup4
- **Frontend:** HTML5, HTMX, Vanilla CSS (Premium Dark Mode)
- **Deployment:** Docker, Docker Compose

## Starten der Anwendung

### Mit Docker Compose (Empfohlen)

Führen Sie im Projektverzeichnis folgenden Befehl aus:

```bash
docker-compose up --build
```

Die Anwendung ist anschließend unter [http://localhost:8000](http://localhost:8000) erreichbar. Die Datenbank wird im lokalen Ordner `./data/deals.db` gespeichert.

### Lokal ausführen (ohne Docker)

1. **Abhängigkeiten installieren:**
   ```bash
   pip install -r requirements.txt
   ```

2. **Server starten:**
   ```bash
   uvicorn app.main:app --reload
   ```

Die Anwendung ist anschließend unter [http://127.0.0.1:8000](http://127.0.0.1:8000) erreichbar.
