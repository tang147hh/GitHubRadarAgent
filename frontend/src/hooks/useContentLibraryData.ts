import { useContentIndexData } from "./useContentIndexData";

/** @deprecated Prefer useContentIndexData for all workspace and library views. */
export function useContentLibraryData() {
  const data = useContentIndexData();
  return { ...data, refresh: data.reload };
}
