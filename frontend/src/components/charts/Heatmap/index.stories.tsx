import type { Meta, StoryObj } from "@storybook/react-vite";

import Heatmap from "./index";

const meta = {
  title: "Components/Charts/Heatmap",
  component: Heatmap,
  parameters: { layout: "padded" },
  tags: ["autodocs"],
} satisfies Meta<typeof Heatmap>;

export default meta;
type Story = StoryObj<typeof meta>;

const xLabels = ["Drug", "Disease", "Symptom", "Procedure"];
const yLabels = ["Run #1", "Run #2", "Run #3"];

// deterministic-looking scores per (run, label)
const scores = [
  [0.55, 0.48, 0.42, 0.5],
  [0.7, 0.66, 0.6, 0.68],
  [0.82, 0.78, 0.71, 0.8],
];

const data = scores.flatMap((row, y) => row.map((value, x) => ({ x, y, value })));

export const RunComparison: Story = {
  args: {
    xLabels,
    yLabels,
    data,
    min: 0,
    max: 1,
  },
};
