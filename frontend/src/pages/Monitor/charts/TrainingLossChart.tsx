import Button from "@components/Button";
import { ChartState, LineChart } from "@components/charts";
import type { TrainingMetric } from "types";

import { CHART } from "../chartColors";
import { buildLossSeries, formatEpoch, formatLoss } from "../chartData";

const CHART_HEIGHT = 280;

interface Props {
  metrics: TrainingMetric[];
  isTraining: boolean;
  /** Jump to the training controls (used by the first-run empty state). */
  onConfigure?: () => void;
}

/** Live training-loss curve with loading / empty / guided-first-run states. */
const TrainingLossChart = ({ metrics, isTraining, onConfigure }: Props) => {
  if (metrics.length > 0) {
    const { xData, loss, evalLoss, hasStep } = buildLossSeries(metrics);
    const hasEvalLoss = evalLoss.some((v) => v !== null);
    return (
      <LineChart
        xData={xData}
        xName={hasStep ? "Step" : "Epoch"}
        yName="Loss"
        showLegend={hasEvalLoss}
        height={CHART_HEIGHT}
        xAxisFormatter={formatEpoch}
        valueFormatter={formatLoss}
        series={[
          { name: "Train loss", data: loss, color: CHART.loss, area: true },
          // connectNulls: eval loss only exists every eval_steps steps; without
          // it the sparse points have no adjacent neighbours and no line renders.
          ...(hasEvalLoss ? [{ name: "Eval loss", data: evalLoss, color: CHART.relaxedF1, connectNulls: true }] : []),
        ]}
      />
    );
  }

  if (isTraining) {
    return <ChartState variant="loading" message="Waiting for training metrics…" height={CHART_HEIGHT} />;
  }

  return (
    <ChartState
      variant="empty"
      title="No training metrics yet"
      message="Pick training datasets and labels above, choose a base model, then start a run to watch the loss curve here in real time."
      height={CHART_HEIGHT}
      action={
        onConfigure && (
          <Button variant="primary" size="small" onClick={onConfigure}>
            Configure a run
          </Button>
        )
      }
    />
  );
};

export default TrainingLossChart;
