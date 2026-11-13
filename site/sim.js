// Monte Carlo of the rest of the regular season. No DOM; the page and node both load it.
//
// league: window.LEAGUE from data.js (teams in current-standings order)
// method: one of league.methods; method.games[k] holds each side's expected points for game k
// locks:  Map(gameIndex -> winning team id) for games the user has decided
// Returns, per team index:
//   seeds[t][s]        sims where team t finished seed s (s = playoffTeams means missed)
//   byRecord[t][w][s]  same, split by w = games team t won from here on
function simulate(league, method, locks, nSims, rngSeed) {
  const teams = league.teams, P = league.playoffTeams, sd = method.sd;
  const idx = new Map(teams.map((t, i) => [t.id, i]));
  const games = league.games.map((g, k) => ({
    h: idx.get(g.home), a: idx.get(g.away),
    hMean: method.games[k].home, aMean: method.games[k].away,
    lockedHome: locks.has(k) ? locks.get(k) === g.home : null,
  }));
  const left = teams.map((_, i) => games.filter((g) => g.h === i || g.a === i).length);

  // mulberry32: small seeded PRNG so the same picks always give the same numbers
  let state = rngSeed | 0;
  const rand = () => {
    state = (state + 0x6d2b79f5) | 0;
    let t = Math.imul(state ^ (state >>> 15), 1 | state);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
  const normal = () => Math.sqrt(-2 * Math.log(1 - rand())) * Math.cos(2 * Math.PI * rand());

  const seeds = teams.map(() => new Array(P + 1).fill(0));
  const byRecord = teams.map((_, i) => Array.from({ length: left[i] + 1 }, () => new Array(P + 1).fill(0)));
  const wins = new Float64Array(teams.length);
  const pf = new Float64Array(teams.length);
  const added = new Int32Array(teams.length);
  const order = teams.map((_, i) => i);

  for (let s = 0; s < nSims; s++) {
    teams.forEach((t, i) => { wins[i] = t.wins + t.ties / 2; pf[i] = t.pf; added[i] = 0; });
    for (const g of games) {
      let hs, as;
      // A locked game redraws until the picked team wins, so its points stay realistic.
      do {
        hs = g.hMean + sd * normal();
        as = g.aMean + sd * normal();
      } while (g.lockedHome !== null && hs > as !== g.lockedHome);
      pf[g.h] += hs;
      pf[g.a] += as;
      const w = hs > as ? g.h : g.a;
      wins[w]++;
      added[w]++;
    }
    order.sort((x, y) => wins[y] - wins[x] || pf[y] - pf[x]);
    order.forEach((i, rank) => {
      const seed = Math.min(rank, P);
      seeds[i][seed]++;
      byRecord[i][added[i]][seed]++;
    });
  }
  return { seeds, byRecord };
}
