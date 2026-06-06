// SPDX-License-Identifier: Apache-2.0
//
// Synthetic agent-network data for the /agents map page.
//
// Coordinates are real-world city longitudes/latitudes.  A small seeded
// PRNG (seeded from each cluster's name) scatters agents around the
// cluster centroid in a stable way, so the layout is the same on every
// page load.  No backend is required; this module is the single source of
// truth for the map until a real /api/agents feed is wired in.

export interface AgentCluster {
  /** Human-readable city / region label. */
  city: string;
  /** Two-letter region code shown beside the city name. */
  region: string;
  /** [longitude, latitude] of the city centroid. */
  coords: [number, number];
  /** Number of agents in this cluster. */
  agents: number;
  /** Optional accent tag — e.g. "Project NANDA", "Anthropic". */
  affiliation?: string;
}

export const clusters: AgentCluster[] = [
  { city: "Cambridge",  region: "US-MA", coords: [-71.106, 42.373], agents: 34, affiliation: "Project NANDA" },
  { city: "San Francisco", region: "US-CA", coords: [-122.419, 37.775], agents: 41 },
  { city: "New York",   region: "US-NY", coords: [-74.006, 40.713], agents: 27 },
  { city: "London",     region: "UK",    coords: [-0.128,  51.507], agents: 22 },
  { city: "Berlin",     region: "DE",    coords: [13.405,  52.520], agents: 15 },
  { city: "Tel Aviv",   region: "IL",    coords: [34.781,  32.085], agents: 12 },
  { city: "Bengaluru",  region: "IN",    coords: [77.594,  12.972], agents: 31 },
  { city: "Singapore",  region: "SG",    coords: [103.819, 1.352],  agents: 18 },
  { city: "Tokyo",      region: "JP",    coords: [139.692, 35.690], agents: 24 },
  { city: "Sydney",     region: "AU",    coords: [151.209, -33.868], agents: 9  },
  { city: "São Paulo",  region: "BR",    coords: [-46.633, -23.550], agents: 11 },
];

/** Total agent count across all clusters. */
export const totalAgents = clusters.reduce((s, c) => s + c.agents, 0);

/** Linear-congruential PRNG seeded from a string. */
function seededRng(seed: string): () => number {
  let s = 0;
  for (let i = 0; i < seed.length; i++) s = (s * 31 + seed.charCodeAt(i)) | 0;
  // Ensure s is non-zero / not divisible by 2147483647
  if (s === 0) s = 1;
  return () => {
    s = (s * 1103515245 + 12345) & 0x7fffffff;
    return s / 0x7fffffff;
  };
}

export interface AgentDot {
  id: string;
  cluster: string;
  /** Lon/lat after jittering around the cluster centroid. */
  coords: [number, number];
}

/** Scatter `c.agents` dots around the cluster centroid using a seeded PRNG. */
export function jitterAgents(c: AgentCluster): AgentDot[] {
  const rng = seededRng(c.city);
  const dots: AgentDot[] = [];
  // Jitter radius in degrees — small enough that clusters stay tight on a world map.
  const radiusDeg = 1.6;
  for (let i = 0; i < c.agents; i++) {
    const angle = rng() * Math.PI * 2;
    // Square-root distribution gives an even visual density inside the disc.
    const r = Math.sqrt(rng()) * radiusDeg;
    dots.push({
      id: `${c.city.toLowerCase().replace(/\s+/g, "-")}-${i}`,
      cluster: c.city,
      coords: [
        c.coords[0] + Math.cos(angle) * r,
        c.coords[1] + Math.sin(angle) * r * 0.7, // squash a bit since lat is shorter at equator
      ],
    });
  }
  return dots;
}

/** Pre-built flat list of every agent dot. */
export const allAgents: AgentDot[] = clusters.flatMap(jitterAgents);

/** A directed link between two clusters used to animate message flow. */
export interface MessageLink {
  fromCity: string;
  toCity: string;
  from: [number, number];
  to: [number, number];
}

/**
 * Pre-compute every ordered pair of distinct clusters once so the page can
 * pick a random one to animate without rebuilding the list each tick.
 */
export const clusterLinks: MessageLink[] = (() => {
  const out: MessageLink[] = [];
  for (let i = 0; i < clusters.length; i++) {
    for (let j = 0; j < clusters.length; j++) {
      if (i === j) continue;
      out.push({
        fromCity: clusters[i].city,
        toCity: clusters[j].city,
        from: clusters[i].coords,
        to: clusters[j].coords,
      });
    }
  }
  return out;
})();
