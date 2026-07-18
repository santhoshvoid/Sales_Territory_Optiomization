# Interview Q&A — Sales Territory Optimization

Likely questions an interviewer (especially at ZS Associates or a similar
commercial-analytics consultancy) could ask about this project, with
answers geared to what's actually implemented here.

---

## Problem framing

**Q: Walk me through the problem and why it matters.**
A: A fixed sales force (200 reps) covers a set of accounts (hospitals) that
grew organically, so coverage drifted out of balance — some reps are
overloaded, some underutilized. Overloaded reps under-serve their accounts
(lower call frequency, worse relationship depth, higher attrition risk);
underutilized reps are a sunk cost the company is overpaying for relative to
their output. The business goal is to redesign territories so effort is
evenly spread and travel is minimized, without needing to hire or fire
anyone — it's a reallocation problem, not a headcount problem.

**Q: Why did you balance on "workload" instead of just hospital count?**
A: Hospital count is a proxy that can be wrong — a rep with 75 small clinics
can have less total work than a rep with 50 large hospitals. Optimizing pure
headcount would "solve" the visible symptom (uneven counts) while leaving
the underlying problem (uneven effort) intact. I used a workload column
(call volume / potential) as the real capacity unit, and hospital count is
just what falls out of that. This is the single most important modeling
decision in the project, and it's the first thing I'd push back on if I saw
someone balance a sales team on raw account count.

**Q: How would you actually get that workload number in a real engagement?**
A: It would come from client data — historical call/visit logs, prescription
or sales volume (in pharma), account revenue, or a physician-count-based
potential score. In absence of good workload data you'd start from a proxy
(e.g. bed count for hospitals, employee count for B2B accounts) and refine
it once real call-activity data becomes available.

---

## Algorithm choices

**Q: Why K-Means and not some other clustering algorithm?**
A: K-Means is the natural fit because we want exactly `k = 200` territories
(one per rep) — that's a hard business constraint, and K-Means is one of the
few clustering algorithms where you specify `k` directly rather than a
density or distance threshold (unlike DBSCAN or hierarchical clustering with
a cut height). It's also fast and well-understood, which matters for
something a client team needs to explain and trust, not just a black box.

**Q: Vanilla K-Means doesn't have a "balance" constraint. How did you handle
that?**
A: Correct — plain K-Means minimizes within-cluster distance only, so
nothing stops it from producing a 120-hospital cluster next to an
18-hospital one. I turned this into what's sometimes called
**"Capacitated K-Means"**: I run K-Means to get good starting geographic
centers, then replace the plain "assign to nearest center" step with
"assign to the nearest center that still has spare workload capacity"
(processing the largest-workload hospitals first so they don't get stranded
once nearby reps fill up), then recompute each center as the
workload-weighted centroid of its new hospitals, and repeat — exactly
Lloyd's algorithm, but with a capacity check injected into the assignment
step.

**Q: Isn't the truly optimal version of this problem just a linear program /
assignment problem? Why not solve it exactly?**
A: It is — the exact version is the **Generalized Assignment Problem**
(each hospital assigned to exactly one rep, capacity constraint per rep,
minimize total distance), which is NP-hard in general. You could formulate
it as an integer program and solve small instances exactly with a solver
like PuLP/OR-Tools, or relax it to a transportation problem (LP) and solve
via min-cost flow if you're willing to allow (and then round) fractional
assignments. I chose the greedy-plus-Lloyd's-iteration heuristic because:
(1) it scales linearly-ish and comfortably handles thousands of accounts,
(2) it naturally keeps every hospital assigned to exactly one rep with no
fractional/split-assignment cleanup step, and (3) it's easy to explain to a
client — "closest rep with room" is intuitive in a way that "dual variables
of a transportation LP" is not. In a real engagement, I'd validate this
heuristic's gap to the LP-relaxation lower bound on a sample to show how
close to optimal it lands.

**Q: Did you actually try a min-cost-flow / LP formulation?**
A: Yes, that was my first implementation, formulated as source → hospital →
rep-center → sink with capacities equal to workload. It has a subtle
correctness bug worth knowing about: min-cost flow guarantees an
*integral* optimal solution exists on integer capacities, but that
integrality is per-edge, not per-hospital — a hospital's workload can still
get split across two rep-center edges (e.g. 30 units to Rep A, 20 to Rep B)
while every edge flow is a whole number. If you then decode "assign each
hospital to whichever rep got the larger share," you silently break the
capacity guarantee, because you're crediting a rep with the hospital's full
workload even though the flow solver only "paid" for part of it. That's
exactly the bug I hit and fixed by switching to the greedy/Lloyd's approach,
which assigns each hospital atomically by construction. I'd mention this
unprompted in an interview — it's a good example of catching your own
mistake and understanding *why* it was wrong, not just that the numbers
looked off.

**Q: How do you use real road distance instead of straight-line distance?**
A: I used the Haversine formula for great-circle distance (correct for
lat/lon on a sphere, unlike naive Euclidean distance on raw coordinates,
which distorts as you move away from the equator). For a production
version I'd swap this for a road-network travel-time matrix from something
like OSRM, Google Distance Matrix API, or a routing engine — straight-line
distance is a reasonable proxy for relative comparisons but understates
actual travel time in areas with rivers, mountains, or poor road
connectivity.

**Q: How do you know your algorithm converges / how many iterations does it
take?**
A: I iterate the assign → recompute-centroid loop until the centers stop
moving meaningfully (mean shift < 1e-4) or a max iteration cap is hit — same
stopping rule as standard K-Means. In practice it converges in 4-8
iterations on a dataset this size. It's not guaranteed to reach the global
optimum (Lloyd's algorithm is a local search — that's true even for
uncapacitated K-Means), so in production I'd run it from a few different
K-Means initializations (`n_init`) and keep the best result by total
distance, exactly like scikit-learn already does internally for plain
K-Means.

---

## Evaluation & metrics

**Q: How do you know the optimization actually worked?**
A: Three metrics, before vs. after: (1) standard deviation / coefficient of
variation of workload per rep — this is the direct balance metric; (2)
standard deviation of hospital count per rep — the "vanity metric" that
matches how the business intuitively describes the problem; (3) average
distance from each hospital to its rep's territory center — the travel
efficiency metric. In the synthetic run, workload CV dropped from 0.61 to
0.17 (a ~73% reduction in imbalance) and average distance dropped by ~89%
because the "before" scenario had no geographic logic at all.

**Q: What's the coefficient of variation and why use it over standard
deviation alone?**
A: CV = std / mean. It's scale-free, so you can compare "how balanced is
this" across runs or datasets even if the average workload per rep changes
(e.g. if you later add more hospitals or change the number of reps). Raw
std dev by itself doesn't tell you whether 30 units of spread is a lot or a
little without knowing the mean.

**Q: What would you tell a client who says "some reps still don't look
equal after your optimization"?**
A: I'd show the capacity tolerance band — I don't force *perfect* equality
(mean exactly for every rep), I allow an explicit tolerance (8% above
average, in this build) because perfectly equal workload usually means
absurd geography (a rep's territory spread across three states to hit an
exact number). There's a real trade-off between balance and compactness,
and the tolerance parameter is how you tune that trade-off transparently
instead of hiding it.

---

## Data & assumptions

**Q: Your data is synthetic — what would be different with real client
data?**
A: Real data brings messiness this synthetic generator doesn't: missing or
stale geocodes, accounts that closed or merged, workload figures that are
themselves estimates with error bars, reps with legal/contractual
restrictions on which accounts they can serve (e.g. licensing by state),
and existing relationships you don't want to blow up (a rep who's spent five
years building trust with a hospital shouldn't be swapped out purely because
an optimizer says so). I'd expect the real engagement to spend more time on
data cleaning and constraint-gathering from the client than on the
optimization algorithm itself — that's usually true in analytics
consulting.

**Q: Why does the "before" scenario include random reassignment noise?**
A: To simulate how real territories actually degrade — not through one bad
decision, but through years of small ad-hoc overrides (a rep leaves and
their accounts get split up quickly without much thought, a new hospital
opens and gets assigned to whoever's available that week). A pure
nearest-neighbor assignment without that noise would already look
reasonably balanced, which wouldn't demonstrate the problem the project is
solving.

---

## Extending the project

**Q: How would you add a "minimize disruption" constraint, so you're not
reassigning everyone at once?**
A: Add a penalty term to the assignment cost: instead of ranking candidate
reps by distance alone, rank by `distance + disruption_penalty *
(current_rep != candidate_rep)`. That biases the optimizer to keep a
hospital with its current rep unless another rep is meaningfully better
(closer or needed for balance), which mirrors how you'd actually roll this
out to a client — nobody wants 100% of accounts changing hands overnight.

**Q: How would this change if reps had different capacities (e.g. senior
reps can handle more)?**
A: Straightforward — right now every rep gets the same `capacity` scalar; I'd
replace that with a per-rep capacity vector (e.g. derived from tenure,
territory type, or contracted hours) and the same greedy/Lloyd's algorithm
works unchanged, since the capacity check is already per-rep, not global.

**Q: How would you scale this to, say, 50,000 accounts and 2,000 reps?**
A: The KD-tree nearest-center lookup already keeps each assignment pass
close to `O(n log k)` instead of the naive `O(n*k)` full distance matrix, so
it scales reasonably as-is. Beyond that I'd look at: (1) parallelizing the
per-hospital assignment step, (2) hierarchical decomposition — cluster into
regions first, then optimize reps within each region independently, which
turns one huge problem into many small, parallelizable ones and matches how
sales organizations are structured anyway (national → regional →
territory).

**Q: What's the single biggest limitation of this approach?**
A: It treats "workload" as a static, known number. Real workload isn't
fixed — it responds to how much attention a rep pays an account (more
visits can grow an account's volume), and territory changes themselves
temporarily disrupt output as reps build new relationships. A one-shot
optimization is a good starting point for a redesign, but a mature version
of this would be a recurring or continuously-updated process, not a
one-time run.
