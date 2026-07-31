import type { Meta, StoryObj } from "@storybook/react-vite";
import { MemoryRouter } from "react-router-dom";
import ActiveModelChip from ".";

const meta: Meta<typeof ActiveModelChip> = {
  title: "Pages/DatasetTermExtraction/ActiveModelChip",
  component: ActiveModelChip,
  tags: ["autodocs"],
  parameters: {
    layout: "centered",
  },
  decorators: [
    (Story) => (
      <MemoryRouter>
        <Story />
      </MemoryRouter>
    ),
  ],
};

export default meta;
type Story = StoryObj<typeof ActiveModelChip>;

export const TrainedModel: Story = {
  args: {
    modelName: "run-7",
  },
};

export const DefaultModel: Story = {
  args: {
    modelName: "Default model",
  },
};
