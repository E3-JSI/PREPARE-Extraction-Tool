import type { Meta, StoryObj } from "@storybook/react-vite";

import { CHART_TOKENS } from "../theme";
import LineChart from "./index";

const meta = {
  title: "Components/Charts/LineChart",
  component: LineChart,
  parameters: { layout: "padded" },
  tags: ["autodocs"],
} satisfies Meta<typeof LineChart>;

export default meta;
type Story = StoryObj<typeof meta>;

const epochs = Array.from({ length: 12 }, (_, i) => i + 1);

export const TrainingLoss: Story = {
  args: {
    xData: epochs,
    xName: "Epoch",
    yName: "Loss",
    showLegend: false,
    series: [
      {
        name: "Loss",
        color: CHART_TOKENS.error,
        area: true,
        data: [2.1, 1.6, 1.25, 1.0, 0.82, 0.7, 0.61, 0.55, 0.5, 0.47, 0.45, 0.44],
      },
    ],
  },
};

export const MultiSeries: Story = {
  args: {
    xData: epochs,
    xName: "Epoch",
    series: [
      {
        name: "Train loss",
        color: CHART_TOKENS.error,
        data: [2.1, 1.6, 1.25, 1.0, 0.82, 0.7, 0.61, 0.55, 0.5, 0.47, 0.45, 0.44],
      },
      {
        name: "Val loss",
        color: CHART_TOKENS.warning,
        data: [2.2, 1.8, 1.5, 1.3, 1.15, 1.05, 1.0, 0.98, 0.97, 0.99, 1.02, 1.05],
      },
    ],
  },
};
