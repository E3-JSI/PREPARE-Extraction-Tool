import type { Meta, StoryObj } from "@storybook/react-vite";
import { fn } from "storybook/test";

import Sidebar from "./index";

const meta = {
  title: "Components/Sidebar",
  component: Sidebar,
  parameters: {
    layout: "fullscreen",
  },
  tags: ["autodocs"],
} satisfies Meta<typeof Sidebar>;

export default meta;
type Story = StoryObj<typeof meta>;

export const Open: Story = {
  args: {
    isOpen: true,
    onClose: fn(),
    title: "Sidebar Title",
    children: (
      <div style={{ padding: "1rem" }}>
        <p>This is the sidebar content.</p>
        <p>You can put any content here.</p>
      </div>
    ),
  },
};

export const Closed: Story = {
  args: {
    isOpen: false,
    onClose: fn(),
    title: "Hidden Sidebar",
    children: <p>This content is not visible when closed.</p>,
  },
};

export const CustomWidth: Story = {
  args: {
    isOpen: true,
    onClose: fn(),
    title: "Wide Sidebar",
    width: "600px",
    children: (
      <div style={{ padding: "1rem" }}>
        <p>This sidebar has a custom width of 600px.</p>
      </div>
    ),
  },
};
