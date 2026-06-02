## Routepass — Komoot to Strava Sync

A lightweight, self-hosted automation service that bridges two fitness platforms: Komoot (used for route planning and outdoor navigation) and Strava (used for activity tracking and social features). After completing a tour on Komoot, the service automatically pushes it to Strava — eliminating the need to upload GPX files manually.

### How It Works

1. **Polling**: A scheduled job polls the Komoot API for new completed tours since the last sync timestamp.
2. **GPX Export**: For each new tour, the GPX track data is fetched from Komoot's tour export endpoint.
3. **Strava Upload**: The GPX file is uploaded to Strava via the Strava API v3, which automatically creates a new activity with the route data.
4. **State Management**: The last successfully synced tour ID is persisted to avoid duplicate uploads across service restarts.

### Deployment

The service runs as a Docker container deployed on a personal Coolify instance. A simple `docker-compose.yml` with an environment-variable-based configuration makes it easy to self-host.

### Why Not Use the Official Integration?

Komoot's official Strava integration only works for manually started recordings on the Komoot app. It doesn't support syncing pre-planned routes navigated via GPS devices, which is the primary use case for this tool.
