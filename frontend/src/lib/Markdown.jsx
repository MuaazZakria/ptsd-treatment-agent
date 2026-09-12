import { useMemo } from "react";
import { marked } from "marked";
import DOMPurify from "dompurify";

marked.setOptions({ gfm: true, breaks: true });

DOMPurify.addHook("afterSanitizeAttributes", (node) => {
  if (node.tagName === "A") {
    node.setAttribute("target", "_blank");
    node.setAttribute("rel", "noreferrer");
  }
});

export default function Markdown({ text, className = "md" }) {
  const html = useMemo(
    () => DOMPurify.sanitize(marked.parse(text || "", { async: false })),
    [text]
  );
  return <div className={className} dangerouslySetInnerHTML={{ __html: html }} />;
}
