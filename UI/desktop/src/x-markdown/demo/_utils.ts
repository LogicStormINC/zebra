import { useState } from "react";

export function useMarkdownTheme() {
  const [theme] = useState("x-markdown");
  return [theme] as const;
}
