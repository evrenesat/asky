# Alpha Program Overview

## Alpha Objective

The Alpha workstream exists to reduce end-user latency and make deployment ownership explicit.
The team set a measurable objective: cut p95 response latency by at least 30 percent while keeping
incident volume flat during the transition period.

## Alpha Rollout Notes

Alpha uses a phased migration with one service boundary per release window. The first wave moved
a synchronous hot path into a Rust service and introduced explicit request budgets. Internal
measurements after the first two waves showed lower tail latency and fewer timeout retries.
