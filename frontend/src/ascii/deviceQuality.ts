// Scales how much work the ASCII backgrounds do per frame based on a
// rough read of the device's processing power ("make sure that the canvas
// is scaled to account for processing power") -- a phone/low-end laptop
// gets a coarser grid and fewer particles, a capable desktop keeps full
// density, rather than every device paying the same per-frame cost
// regardless of whether it can actually keep up.
//
// navigator.hardwareConcurrency (core count) is used as the signal, not a
// live FPS probe: it's synchronous, available before the first frame even
// renders (so there's no visible "start heavy, then drop resolution"
// stutter), and supported in every browser that matters here. It's a
// coarse proxy -- a device's actual per-frame budget also depends on GPU,
// thermal throttling, and what else is running -- but it correlates well
// enough with "how much can this device chew through per frame" to be
// worth acting on, and errs toward the safer (lower) tier when it can't
// tell (`hardwareConcurrency` is 0/undefined on some privacy-hardened
// browsers).
export type QualityTier = "low" | "medium" | "high";

export function getQualityTier(): QualityTier {
  if (typeof navigator === "undefined") return "medium";
  const cores = navigator.hardwareConcurrency || 0;
  if (cores === 0) return "medium"; // unknown -- assume mid-range rather than penalizing or over-trusting
  if (cores <= 2) return "low";
  if (cores <= 4) return "medium";
  return "high";
}

// Multiplier applied to a component's "full quality" budget (character-
// grid cell count, particle counts, etc.) -- 1.0 leaves high-end devices
// unchanged from the original hand-tuned density; low-end devices get
// roughly half the cells to push per frame, which is where the DOM/canvas
// paint cost scales from.
export function getQualityMultiplier(tier: QualityTier = getQualityTier()): number {
  switch (tier) {
    case "low":
      return 0.55;
    case "medium":
      return 0.8;
    case "high":
      return 1;
  }
}
