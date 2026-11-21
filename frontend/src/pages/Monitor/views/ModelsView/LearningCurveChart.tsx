import { ChartState, LineChart } from "@components/charts";
import type { LearningCurvePoint } from "types";

import { CHART } from "../../chartColors";

const CHART_HEIGHT = 280;

interface LearningCurveChartProps {
  points: LearningCurvePoint[];
  baselineMacroF1?: number | null;
}

const LearningCurveChart = ({
  points,
  baselineMacroF1,
}: LearningCurveChartProps) => {
  const sortedPoints = [...points].sort(
    (a, b) =>
      a.num_train_documents - b.num_train_documents ||
      a.run_id - b.run_id
  );

  const baselineValue =
    typeof baselineMacroF1 === "number" &&
    Number.isFinite(baselineMacroF1)
      ? baselineMacroF1
      : null;

  const xData = [
    ...(baselineValue === null ? [] : [0]),
    ...sortedPoints.map(
      (point) => point.num_train_documents
    ),
  ];

  const f1Data = [
    ...(baselineValue === null ? [] : [baselineValue]),
    ...sortedPoints.map((point) => point.macro_f1),
  ];

  if (xData.length === 0) {
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
        xData={xData}
        xAxisType="value"
        xName="Training documents"
        yName="Macro F1"
        yMin={0}
        yMax={1}
        height={CHART_HEIGHT}
        showLegend={false}
        notMerge
        xAxisFormatter={(value) => {
          const numericValue = Number(value);

          return baselineValue !== null && numericValue === 0
            ? "Base model"
            : numericValue.toLocaleString();
        }}
        valueFormatter={(value) =>
          `${(value * 100).toFixed(1)}%`
        }
        series={[
          {
            name: "Macro F1",
            data: f1Data,
            color: CHART.exactF1,
            smooth: false,
            showSymbol: true,
          },
        ]}
      />

      {xData.length === 1 && (
        <p role="note">
          {baselineValue !== null
            ? "Only the base model result is available."
            : "One completed run is available. Train the same base model with a different amount of data to form a learning curve."}
        </p>
      )}
    </>
  );
};

export default LearningCurveChart;