# Futbol Americano playoff odds

Monte Carlo playoff odds for the ESPN fantasy league "Futbol Americano 2K26": pick winners of remaining games and see every team's seed odds, remaining schedule and odds by final record.

Site: https://jacksonroah.github.io/futbol-americano-playoff/

- `fetch.py` pulls the league from ESPN (stdlib only) and writes `site/data.js`.
- `site/sim.js` runs the simulation in the browser; `site/index.html` is the page.
- `.github/workflows/update.yml` re-pulls the data and redeploys every morning.

Run locally: `python3 fetch.py`, then open `site/index.html`.
