import { describe, expect, it } from "vitest";

import type { TrainingMetric } from "types";

import { buildLossSeries } from "../chartData";

describe("buildLossSeries", () => {
  it("coalesces the train-loss and eval-loss rows for the same step into one point", () => {
    // The trainer streams train loss and eval loss for a step as separate rows.
    const metrics: TrainingMetric[] = [
      { step: 1, epoch: 0, loss: 5, eval_loss: null },
      { step: 1, epoch: 0, loss: null, eval_loss: 4 },
      { step: 2, epoch: 0, loss: 3, eval_loss: null },
      { step: 2, epoch: 0, loss: null, eval_loss: 2 },
    ];

    const series = buildLossSeries(metrics);

    expect(series.hasStep).toBe(true);
    expect(series.xData).toEqual([1, 2]);
    expect(series.loss).toEqual([5, 3]);
    expect(series.evalLoss).toEqual([4, 2]);
  });

  it("drops step-less orphan rows when step rows exist", () => {
    // epoch_update orphans (no step) duplicate the step rows and must not appear
    // as stray trailing x-categories.
    const metrics: TrainingMetric[] = [
      { step: null, epoch: 0, loss: 5, eval_loss: null },
      { step: 1, epoch: 0, loss: 5, eval_loss: null },
      { step: 1, epoch: 0, loss: null, eval_loss: 4 },
      { step: null, epoch: 1, loss: 3, eval_loss: null },
      { step: 2, epoch: 1, loss: 3, eval_loss: null },
    ];

    const series = buildLossSeries(metrics);

    expect(series.xData).toEqual([1, 2]);
    expect(series.loss).toEqual([5, 3]);
    expect(series.evalLoss).toEqual([4, null]);
  });

  it("sorts coalesced points by step regardless of arrival order", () => {
    const metrics: TrainingMetric[] = [
      { step: 3, epoch: 1, loss: 1, eval_loss: null },
      { step: 1, epoch: 0, loss: 5, eval_loss: null },
      { step: 2, epoch: 0, loss: 3, eval_loss: null },
    ];

    expect(buildLossSeries(metrics).xData).toEqual([1, 2, 3]);
    expect(buildLossSeries(metrics).loss).toEqual([5, 3, 1]);
  });

  it("keeps every row in epoch order for legacy step-less runs (no coalescing)", () => {
    // Legacy runs only persisted epoch_update rows: epoch is int-truncated so
    // values repeat, but each row is a distinct loss point and must be preserved.
    const metrics: TrainingMetric[] = [
      { step: null, epoch: 0, loss: 9, eval_loss: null },
      { step: null, epoch: 0, loss: 8, eval_loss: null },
      { step: null, epoch: 1, loss: 7, eval_loss: null },
    ];

    const series = buildLossSeries(metrics);

    expect(series.hasStep).toBe(false);
    expect(series.xData).toEqual([0, 0, 1]);
    expect(series.loss).toEqual([9, 8, 7]);
  });

  it("returns empty series for no metrics", () => {
    const series = buildLossSeries([]);
    expect(series).toEqual({ xData: [], loss: [], evalLoss: [], hasStep: false });
  });
});
