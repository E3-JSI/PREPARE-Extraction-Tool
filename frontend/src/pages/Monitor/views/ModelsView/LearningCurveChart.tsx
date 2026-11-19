import { ChartState, LineChart } from "@components/charts";
import type { LearningCurvePoint } from "types";

import { CHART } from "../../chartColors";

const CHART_HEIGHT = 280;

interface LearningCurveChartProps {
  points: LearningCurvePoint[];
}

const LearningCurveChart = ({
  points,
}: LearningCurveChartProps) => {
  const sortedPoints = [...points].sort(
    (a, b) =>
      a.num_train_documents - b.num_train_documents ||
      a.run_id - b.run_id
  );

  if (sortedPoints.length === 0) {
    return (
      <ChartState
        variant="empty"
        title="No learning curve data"
        message="No comparable completed runs with evaluation results are available."
        height={CHART_HEIGHT}
      />
    );
  }

  return (
    <>
      <LineChart
        xData={sortedPoints.map(
          (point) => point.num_train_documents
        )}
        xAxisType="value"
        xName="Training documents"
        yName="Macro F1"
        yMin={0}
        yMax={1}
        height={CHART_HEIGHT}
        showLegend={false}
        notMerge
        xAxisFormatter={(value) =>
          Number(value).toLocaleString()
        }
        valueFormatter={(value) =>
          `${(value * 100).toFixed(1)}%`
        }
        series={[
          {
            name: "Macro F1",
            data: sortedPoints.map(
              (point) => point.macro_f1
            ),
            color: CHART.exactF1,
            smooth: false,
            showSymbol: true,
          },
        ]}
      />

      {sortedPoints.length === 1 && (
        <p role="note">
          One completed run is available. Train the same base
          model with a different amount of data to form a
          learning curve.
        </p>
      )}
    </>
  );
};

export default LearningCurveChart;