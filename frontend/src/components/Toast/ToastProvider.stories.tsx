import { useRef } from "react";
import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, userEvent, within } from "storybook/test";

import Button from "@components/Button";
import { useToastApi } from "@hooks/useToast";

import ToastProvider from "./ToastProvider";

/**
 * Context consumer that counts its own renders. Showing a toast must NOT bump
 * the count — toast state lives in the provider and only the ToastContainer
 * rerenders (the regression this guards against rerendered the whole page).
 */
const RenderCounter = () => {
  const renders = useRef(0);
  renders.current += 1;
  const toast = useToastApi();

  return (
    <div>
      <span data-testid="render-count">{renders.current}</span>
      <Button onClick={() => toast.success("Saved!")}>Show toast</Button>
    </div>
  );
};

const meta = {
  title: "Components/ToastProvider",
  component: ToastProvider,
} satisfies Meta<typeof ToastProvider>;

export default meta;
type Story = StoryObj<typeof meta>;

export const ChildrenDoNotRerenderOnToast: Story = {
  args: {
    children: <RenderCounter />,
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const before = canvas.getByTestId("render-count").textContent;

    await userEvent.click(canvas.getByRole("button", { name: "Show toast" }));

    await expect(canvas.getByText("Saved!")).toBeInTheDocument();
    await expect(canvas.getByTestId("render-count").textContent).toBe(before);
  },
};
