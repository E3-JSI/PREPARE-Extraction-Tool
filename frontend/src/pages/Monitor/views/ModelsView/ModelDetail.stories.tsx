import type { Meta, StoryObj } from "@storybook/react-vite";

import { ModelDetail } from ".";

const meta = {
  title: "Monitor/ModelDetail",
  component: ModelDetail,
  parameters: { layout: "padded" },
  tags: ["autodocs"],
} satisfies Meta<typeof ModelDetail>;

export default meta;
type Story = StoryObj<typeof meta>;

/** A fully trained model with loss curve, per-label eval, and training stats. */
export const TrainedModel: Story = {
  args: {
    detail: {
      model_id: 1,
      run_id: 11,
      base_model: "urchade/gliner_small-v2.1",
      train_dataset_ids: [3, 4],
      eval_dataset_ids: [],
      train_stats: {
        record_count: 120,
        term_count: 540,
        label_distribution: { Drug: 240, Disease: 180, Symptom: 120 },
        reviewed_record_count: 90,
        reviewed_term_count: 410,
        reviewed_label_distribution: { Drug: 190, Disease: 130, Symptom: 90 },
      },
      labels: ["Drug", "Disease", "Symptom"],
      per_label_baseline: {
        Drug: { exact_f1: 0.62, precision: 0.65, recall: 0.59 },
        Disease: { exact_f1: 0.55, precision: 0.58, recall: 0.52 },
        Symptom: { exact_f1: 0.48, precision: 0.5, recall: 0.46 },
      },
      per_label_trained: {
        Drug: { exact_f1: 0.81, precision: 0.84, recall: 0.78 },
        Disease: { exact_f1: 0.74, precision: 0.76, recall: 0.72 },
        Symptom: { exact_f1: 0.68, precision: 0.7, recall: 0.66 },
      },
    },
    metrics: [
      { epoch: 1, loss: 0.842, step: 50, eval_loss: 0.91 },
      { epoch: 2, loss: 0.631, step: 100, eval_loss: 0.73 },
      { epoch: 3, loss: 0.487, step: 150, eval_loss: 0.59 },
      { epoch: 4, loss: 0.374, step: 200, eval_loss: 0.48 },
      { epoch: 5, loss: 0.298, step: 250, eval_loss: 0.41 },
    ],
  },
};

/** The Default (bioner) row — no training history, no detail fetch. */
export const DefaultModel: Story = {
  args: {
    detail: null,
    metrics: [],
  },
};
