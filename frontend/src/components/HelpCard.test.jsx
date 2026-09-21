import { afterEach, expect, test, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import BduiRenderer from "./BduiRenderer";

afterEach(cleanup);

const helpCard = {
  type: "help_card",
  title: "Here's how I can assist you:",
  features: [
    {
      icon: "pen-tool",
      title: "Log your reading",
      description: "Record pages you've read.",
      example: '"Log 20 pages for Dune"',
    },
  ],
};

test("clicking an example sends it as a typed message, not an action", () => {
  const onSend = vi.fn();
  const onAction = vi.fn();
  render(<BduiRenderer element={helpCard} onSend={onSend} onAction={onAction} />);

  fireEvent.click(screen.getByText('"Log 20 pages for Dune"'));

  expect(onSend).toHaveBeenCalledWith("Log 20 pages for Dune");
  expect(onAction).not.toHaveBeenCalled();
});

test("examples inside a composite reach the same handler", () => {
  const onSend = vi.fn();
  render(
    <BduiRenderer element={{ type: "composite", elements: [helpCard] }} onSend={onSend} />,
  );

  fireEvent.click(screen.getByText('"Log 20 pages for Dune"'));

  expect(onSend).toHaveBeenCalledWith("Log 20 pages for Dune");
});
