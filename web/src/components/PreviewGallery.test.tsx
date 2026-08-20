import { afterEach, describe, expect, it } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import PreviewGallery from "./PreviewGallery";

afterEach(() => {
  cleanup();
});

describe("PreviewGallery", () => {
  it("renders nothing for a job with no preview/pdf artifacts", () => {
    const { container } = render(<PreviewGallery jobId="job-1" artifacts={["pptx", "manifest"]} />);
    expect(container).toBeEmptyDOMElement();
  });

  it("renders a thumbnail per preview-N artifact in slide order", () => {
    render(
      <PreviewGallery jobId="job-1" artifacts={["preview-1", "pptx", "preview-0", "pdf"]} />
    );
    const images = screen.getAllByRole("img");
    expect(images.map((img) => img.getAttribute("alt"))).toEqual(["preview-0", "preview-1"]);
  });

  it("expands one thumbnail at a time on click, toggling on a second click", () => {
    render(<PreviewGallery jobId="job-1" artifacts={["preview-0", "preview-1"]} />);
    const [first, second] = screen.getAllByRole("img");

    expect(first).not.toHaveClass("preview-gallery__image--expanded");
    fireEvent.click(first);
    expect(first).toHaveClass("preview-gallery__image--expanded");
    expect(second).not.toHaveClass("preview-gallery__image--expanded");

    // Clicking a different thumbnail swaps which one is expanded.
    fireEvent.click(second);
    expect(first).not.toHaveClass("preview-gallery__image--expanded");
    expect(second).toHaveClass("preview-gallery__image--expanded");

    // Clicking the currently-expanded one again collapses it.
    fireEvent.click(second);
    expect(second).not.toHaveClass("preview-gallery__image--expanded");
  });

  it("keeps the PDF collapsed by default and only mounts the iframe once expanded", () => {
    render(<PreviewGallery jobId="job-1" artifacts={["pdf"]} />);

    expect(screen.queryByTitle("Preview PDF")).not.toBeInTheDocument();
    fireEvent.click(screen.getByText("Show PDF preview"));
    expect(screen.getByTitle("Preview PDF")).toHaveAttribute(
      "src",
      "/api/jobs/job-1/artifacts/pdf"
    );
  });
});
