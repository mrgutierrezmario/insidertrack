import { useEffect } from "react";

/** Sets the tab title as "<page> · InsiderTrack"; restores the bare name on unmount. */
export default function useDocumentTitle(title: string | null | undefined) {
  useEffect(() => {
    document.title = title ? `${title} · InsiderTrack` : "InsiderTrack";
    return () => { document.title = "InsiderTrack"; };
  }, [title]);
}
