import type { Meta, StoryObj } from "@storybook/react-vite";

import TrainingLossChart from "./TrainingLossChart";

const meta = {
  title: "Monitor/TrainingLossChart",
  component: TrainingLossChart,
  parameters: { layout: "padded" },
  tags: ["autodocs"],
} satisfies Meta<typeof TrainingLossChart>;

export default meta;
type Story = StoryObj<typeof meta>;

/** Train-only metrics: a basic descending loss curve over 5 steps. */
export const TrainOnly: Story = {
  args: {
    isTraining: false,
    metrics: [
      { epoch: 1, loss: 0.95, step: 10 },
      { epoch: 1, loss: 0.82, step: 20 },
      { epoch: 2, loss: 0.71, step: 30 },
      { epoch: 2, loss: 0.63, step: 40 },
      { epoch: 3, loss: 0.55, step: 50 },
    ],
  },
};

/**
 * Train + eval metrics: the eval loss starts higher and diverges (overfit
 * scenario) so the two series are visually distinct.
 */
export const TrainAndEval: Story = {
  args: {
    isTraining: false,
    metrics: [
      { epoch: 1, loss: 0.92, step: 10, eval_loss: 0.98 },
      { epoch: 1, loss: 0.78, step: 20, eval_loss: 0.85 },
      { epoch: 2, loss: 0.63, step: 30, eval_loss: 0.74 },
      { epoch: 2, loss: 0.51, step: 40, eval_loss: 0.68 },
      { epoch: 3, loss: 0.41, step: 50, eval_loss: 0.65 },
      { epoch: 3, loss: 0.33, step: 60, eval_loss: 0.67 },
      { epoch: 4, loss: 0.27, step: 70, eval_loss: 0.72 },
    ],
  },
};

/** Live training — shows the loading placeholder state. */
export const LiveTraining: Story = {
  args: {
    isTraining: true,
    metrics: [],
  },
};
