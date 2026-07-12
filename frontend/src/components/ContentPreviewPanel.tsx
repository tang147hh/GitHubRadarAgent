import type { Language } from "../i18n";
import type { ContentItem, ContentVariant } from "../types";
import { ContentDetailPanel, type EditorMode } from "./ContentDetailPanel";

type Props = {
  item: ContentItem | null;
  variant: ContentVariant | null;
  markdownContent: string;
  markdownPath?: string;
  language: Language;
  loading?: boolean;
  error?: string | null;
  onClose?: () => void;
  onOpenLibrary?: (contentId: string, variant: ContentVariant) => void;
  initialMode?: EditorMode;
};

export function ContentPreviewPanel(props: Props) {
  return <ContentDetailPanel {...props} />;
}
