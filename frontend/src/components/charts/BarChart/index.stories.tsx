import type { Meta, StoryObj } from "@storybook/react-vite";

import { CHART_TOKENS } from "../theme";
import BarChart from "./index";

const meta = {
  title: "Components/Charts/BarChart",
  component: BarChart,
  parameters: { layout: "padded" },
  tags: ["autodocs"],
} satisfies Meta<typeof BarChart>;

export default meta;
type Story = StoryObj<typeof meta>;

export const PerLabelMetrics: Story = {
  args: {
    categories: ["Drug", "Disease", "Symptom", "Procedure"],
    yMin: 0,
    yMax: 1,
    series: [
      { name: "Exact F1", color: CHART_TOKENS.success, data: [0.82, 0.74, 0.68, 0.79] },
      { name: "Relaxed F1", color: CHART_TOKENS.warning, data: [0.88, 0.81, 0.75, 0.85] },
      { name: "Precision", color: CHART_TOKENS.primary, data: [0.85, 0.78, 0.71, 0.82] },
      { name: "Recall", color: CHART_TOKENS.info, data: [0.8, 0.72, 0.66, 0.77] },
    ],
  },
};

export const SingleSeries: Story = {
  args: {
    categories: ["Run 1", "Run 2", "Run 3", "Run 4", "Run 5"],
    yMin: 0,
    yMax: 1,
    showLegend: false,
    series: [{ name: "Exact F1", color: CHART_TOKENS.primary, data: [0.62, 0.71, 0.74, 0.79, 0.81] }],
  },
};
