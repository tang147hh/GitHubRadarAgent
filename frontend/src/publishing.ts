import { fetchPublishingExport } from "./api";
import type { ContentItem, ContentVariant, PublishingExport } from "./types";

export function getBestPublishVariant(item: ContentItem): Exclude<ContentVariant, "report"> {
  if (item.has_manual_edit && item.manual_edit_path) return "manual";
  if (item.publish_path) return "publish";
  if (item.package_path) return "package";
  return "source";
}

export function exportContentMarkdown(item: ContentItem): Promise<PublishingExport> {
  return fetchPublishingExport(item.content_id);
}
